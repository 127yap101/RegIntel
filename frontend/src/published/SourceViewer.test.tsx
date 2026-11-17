import { act, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { decode } from './api'
import fixture from './fixtures.generated.json'
import { SourceViewer } from './SourceViewer'

const pdf = vi.hoisted(() => ({
  load: vi.fn<() => { promise: Promise<unknown>; destroy: () => Promise<void> }>(),
}))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({
  AnnotationMode: { DISABLE: 0 },
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: () => pdf.load(),
}))

const source = decode('evidence', fixture.evidence)
function pending() {
  return { promise: new Promise<never>(() => {}), destroy: vi.fn<() => Promise<void>>().mockResolvedValue(undefined) }
}
beforeEach(() => { pdf.load.mockReset() })

describe('source viewer loading lifetime', () => {
  it('creates one PDF worker for the surviving StrictMode setup and destroys it on unmount', async () => {
    const task = pending()
    pdf.load.mockReturnValue(task)
    const view = render(<StrictMode><SourceViewer source={source} bytes={new Uint8Array([1])} /></StrictMode>)
    await waitFor(() => expect(pdf.load).toHaveBeenCalledTimes(1))
    expect(task.destroy).not.toHaveBeenCalled()
    view.unmount()
    expect(task.destroy).toHaveBeenCalledTimes(1)
  })

  it('does not start PDF work after an immediate unmount', async () => {
    pdf.load.mockReturnValue(pending())
    const view = render(<SourceViewer source={source} bytes={new Uint8Array([1])} />)
    view.unmount()
    await act(async () => { await Promise.resolve() })
    expect(pdf.load).not.toHaveBeenCalled()
  })

  it('clears an earlier render error and destroys the old task when source bytes change', async () => {
    const failed = { promise: Promise.reject<never>(new Error('Authored render failure')), destroy: vi.fn<() => Promise<void>>().mockResolvedValue(undefined) }
    const next = pending()
    pdf.load.mockReturnValueOnce(failed).mockReturnValue(next)
    const view = render(<SourceViewer source={source} bytes={new Uint8Array([1])} />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('could not be rendered'))
    view.rerender(<SourceViewer source={source} bytes={new Uint8Array([2])} />)
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(screen.getByRole('status')).toHaveTextContent('Rendering verified source')
    expect(failed.destroy).toHaveBeenCalledTimes(1)
    expect(pdf.load).toHaveBeenCalledTimes(2)
    view.unmount()
    expect(next.destroy).toHaveBeenCalledTimes(1)
  })

  it.each(['verified', 'geometry-mismatch', 'render-error'])('only counts a successfully rendered exact source as inspected: %s', async (mode) => {
    const geometry = source.evidence.record.page_geometry
    const box = geometry.crop_box
    const page = {
      view: [box.x0, box.y0, box.x1 + (mode === 'geometry-mismatch' ? 20 : 0), box.y1],
      rotate: geometry.rotation,
      getViewport: () => ({ width: 1000, height: 1000, convertToViewportPoint: (x: number, y: number) => [x, y] }),
      render: () => ({ promise: mode === 'render-error' ? Promise.reject(new Error('Authored failed render')) : Promise.resolve(), cancel: vi.fn() }),
    }
    pdf.load.mockReturnValue({ promise: Promise.resolve({ getPage: () => Promise.resolve(page) }), destroy: vi.fn<() => Promise<void>>().mockResolvedValue(undefined) })
    const verified = vi.fn<(id: string) => void>()
    render(<SourceViewer source={source} bytes={new Uint8Array([1])} onVerified={verified} />)
    if (mode === 'render-error') await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('could not be rendered'))
    else await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(mode === 'verified' ? 'Source verified · page rendered' : 'stored geometry does not match'))
    if (mode === 'verified') expect(verified).toHaveBeenCalledExactlyOnceWith(source.evidence.record.id)
    else expect(verified).not.toHaveBeenCalled()
  })
})
