import { useEffect, useState } from 'react'
import { Button } from '../components/Button'
import { ModuleApi } from './api'
import type { GlossaryHistory as History } from './generated'

export function GlossaryHistory({ api, selected, busy, onSelect }: { api: ModuleApi; selected: string | null; busy: boolean; onSelect: (version: string) => void }) {
  const [page, setPage] = useState<History | null>(null)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setPage(null)
    void api.read('glossary_history', `/v1/learning/versions?offset=${offset}&limit=20`, controller.signal).then((value) => {
      if (value.offset !== offset || value.limit !== 20) throw new Error('The published history differs from the selected page.')
      if (!controller.signal.aborted) setPage(value)
    }).catch((failure: unknown) => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Published glossary history is unavailable.') }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [api, offset])
  return <section className="rounded-xl border border-line bg-white p-5" aria-labelledby="glossary-history-heading">
    <h3 id="glossary-history-heading" className="font-semibold">Published glossary history</h3>
    <p className="mt-2 text-sm text-muted">Select a published version to read its reviewed definitions. Refresh the reviewed glossary to return to the current version.</p>
    {loading && <p role="status" className="mt-3 text-sm">Loading published versions…</p>}
    {page && page.items.length > 0 && <ol className="mt-3 space-y-3">{page.items.map((item) => <li key={item.glossary_version_id} className="text-sm">
      <p className="break-all">{item.glossary_version_id}{item.glossary_version_id === page.head_glossary_version_id ? ' · current' : ''} · {item.definition_count} reviewed definitions</p>
      <Button variant="secondary" className="mt-2 max-w-full break-all text-left" disabled={busy || loading || selected === item.glossary_version_id} onClick={() => onSelect(item.glossary_version_id)}>View glossary version {item.glossary_version_id}</Button>
    </li>)}</ol>}
    {page && page.total === 0 && <p className="mt-3 text-sm">No published glossary versions.</p>}
    <div className="mt-3 flex flex-wrap gap-3">
      {offset > 0 && <Button variant="secondary" disabled={busy || loading} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous glossary versions</Button>}
      {page && page.offset + page.items.length < page.total && <Button variant="secondary" disabled={busy || loading} onClick={() => setOffset(offset + 20)}>Older glossary versions</Button>}
    </div>
    {error && <p role="alert" className="mt-3 text-sm">{error}</p>}
  </section>
}
