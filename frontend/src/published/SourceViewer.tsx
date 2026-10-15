import { useEffect, useRef, useState } from 'react'
import { AnnotationMode, getDocument, GlobalWorkerOptions } from 'pdfjs-dist/legacy/build/pdf.mjs'
import type { RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import type { PublishedEvidence } from './api'
import { geometryMatches, highlightBox } from './geometry'
import type { Highlight } from './geometry'

GlobalWorkerOptions.workerSrc = workerUrl

export function SourceViewer({ source, bytes }: { source: PublishedEvidence; bytes: Uint8Array<ArrayBuffer> }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [rendered, setRendered] = useState<{ width: number; height: number; boxes: Highlight[]; geometry: boolean } | null>(null)
  const [error, setError] = useState('')
  const record = source.evidence.record
  useEffect(() => {
    let active = true
    let rendering: RenderTask | undefined
    const loading = getDocument({ data: bytes.slice(), useWorkerFetch: false, useWasm: false, enableXfa: false, disableAutoFetch: true, disableRange: true, disableStream: true, stopAtErrors: true })
    void loading.promise.then(async (pdf) => {
      const page = await pdf.getPage(record.source.page_index + 1)
      if (!active || !canvas.current) return
      const viewport = page.getViewport({ scale: 1.1 })
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
      if (viewport.width * viewport.height * pixelRatio * pixelRatio > 16_000_000) throw new Error('Page bound')
      canvas.current.width = Math.ceil(viewport.width * pixelRatio)
      canvas.current.height = Math.ceil(viewport.height * pixelRatio)
      canvas.current.style.width = `${viewport.width}px`
      canvas.current.style.height = `${viewport.height}px`
      rendering = page.render({ canvas: canvas.current, viewport, transform: [pixelRatio, 0, 0, pixelRatio, 0, 0], annotationMode: AnnotationMode.DISABLE })
      await rendering.promise
      if (!active) return
      const geometry = geometryMatches(record.page_geometry, page.view, page.rotate)
      const boxes = geometry ? record.boxes.map((box) => highlightBox(box, viewport)).filter((box): box is Highlight => box !== null) : []
      setRendered({ width: viewport.width, height: viewport.height, boxes, geometry })
    }).catch(() => { if (active) setError('This source page could not be rendered. Exact support and source details remain below.') })
    return () => { active = false; rendering?.cancel(); void loading.destroy() }
  }, [bytes, record])

  return <section aria-label="Exact source page" className="mt-6 rounded-xl border border-line bg-white p-5">
    <h3 className="text-lg font-semibold">Source page {record.source.page_index + 1}</h3>
    <p className="mt-2 text-sm text-muted">Highlighted regions locate the persisted evidence. The exact quoted spans are listed below.</p>
    {error ? <p role="alert" className="mt-3">{error}</p> : <p role="status" className="mt-3 text-sm">{rendered ? rendered.geometry ? 'Source verified · page rendered' : 'Page rendered; stored geometry does not match, so highlights are unavailable.' : 'Rendering verified source…'}</p>}
    <div className="mt-4 max-h-[70vh] max-w-full overflow-auto rounded border border-line bg-paper" tabIndex={0} aria-label="Scrollable PDF page">
      <div className="relative" style={rendered ? { width: rendered.width, height: rendered.height } : undefined}>
        <canvas ref={canvas} aria-label={`Original filing page ${record.source.page_index + 1}`} />
        {rendered?.boxes.map((box, index) => <div key={index} data-testid="evidence-region" className="pointer-events-none absolute border-2 border-amber bg-amber/15" style={box} />)}
      </div>
    </div>
    <dl className="mt-4 space-y-2 break-all text-xs text-muted"><div><dt className="font-semibold">Evidence ID</dt><dd>{record.id}</dd></div><div><dt className="font-semibold">Filing version</dt><dd>{record.source.filing_version_id}</dd></div><div><dt className="font-semibold">Source SHA256</dt><dd>{source.evidence.source_sha256}</dd></div></dl>
    <h4 className="mt-5 font-semibold">Exact support</h4>
    {[...source.supports.map((span) => ({ span, role: 'Disclosure' })), ...source.context_supports.map((witness) => ({ span: witness.span, role: witness.role }))].map(({ span, role }, index) => <div key={index} className="mt-3 border-l-2 border-sage pl-3"><p className="text-xs text-muted">{role} · block characters {span.start}–{span.end} (end exclusive)</p><blockquote className="mt-1 whitespace-pre-wrap text-sm leading-6">{span.quote}</blockquote></div>)}
  </section>
}
