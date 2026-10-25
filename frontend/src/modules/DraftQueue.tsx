import { useEffect, useState } from 'react'
import { Button } from '../components/Button'
import { ModuleApi } from './api'
import type { DefinitionQueue } from './generated'

const states = ['ALL', 'PENDING_REVIEW', 'APPROVED', 'REJECTED'] as const
const inputClass = 'mt-1 min-h-11 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm'

export function DraftQueue({ api, onOpen }: { api: ModuleApi; onOpen: (identity: string) => void }) {
  const [filter, setFilter] = useState<DefinitionQueue['state']>('PENDING_REVIEW')
  const [term, setTerm] = useState('')
  const [selection, setSelection] = useState({ state: filter, query: '', offset: 0 })
  const [revision, setRevision] = useState(0)
  const [page, setPage] = useState<DefinitionQueue | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    const query = new URLSearchParams({ state: selection.state, q: selection.query, offset: String(selection.offset), limit: '20' })
    void api.read('drafts', `/v1/learning/drafts?${query}`, controller.signal).then((value) => {
      if (value.state !== selection.state || value.query !== selection.query || value.offset !== selection.offset) throw new Error('The draft queue differs from the selected filter.')
      if (!controller.signal.aborted) { setPage(value); setError('') }
    }).catch((failure: unknown) => { if (!controller.signal.aborted) { setPage(null); setError(failure instanceof Error ? failure.message : 'The draft queue is unavailable.') } })
    return () => controller.abort()
  }, [api, selection, revision])
  return <section className="rounded-lg border border-line bg-white p-4" aria-labelledby="draft-queue-heading">
    <h4 id="draft-queue-heading" className="font-semibold">Saved definition drafts</h4>
    <p className="mt-2 text-sm text-muted">Find an existing draft and its recorded review. Opening it does not create a new decision or publish content.</p>
    <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); setPage(null); setSelection({ state: filter, query: term, offset: 0 }) }}>
      <label className="text-sm">Draft review state<select className={inputClass} value={filter} onChange={(event) => setFilter(states.find((value) => value === event.target.value) ?? 'ALL')}>{states.map((state) => <option key={state} value={state}>{state.replaceAll('_', ' ')}</option>)}</select></label>
      <label className="text-sm">Search draft term<input className={inputClass} value={term} maxLength={120} onChange={(event) => setTerm(event.target.value)} /></label>
      <Button type="submit" variant="secondary">Apply draft filters</Button>
      <Button variant="secondary" onClick={() => setRevision((value) => value + 1)}>Refresh draft queue</Button>
    </form>
    {page && <>
      <p className="mt-4 text-xs text-muted">{page.total} matching drafts · {page.state.replaceAll('_', ' ')}</p>
      {page.items.length ? <ul className="mt-3 space-y-3">{page.items.map((item) => <li key={item.definition.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-paper p-3"><div className="min-w-0"><p className="break-words text-sm font-semibold">{item.definition.draft.term}</p><p className="mt-1 text-xs text-muted">{item.state.replaceAll('_', ' ')}</p></div><Button variant="secondary" onClick={() => onOpen(item.definition.id)}>Open {item.definition.draft.term}</Button></li>)}</ul> : <p className="mt-3 text-sm">No drafts match these filters.</p>}
      <div className="mt-4 flex gap-3"><Button variant="secondary" disabled={page.offset === 0} onClick={() => { setPage(null); setSelection({ ...selection, offset: Math.max(0, page.offset - page.limit) }) }}>Previous drafts</Button><Button variant="secondary" disabled={page.offset + page.items.length >= page.total} onClick={() => { setPage(null); setSelection({ ...selection, offset: page.offset + page.limit }) }}>Next drafts</Button></div>
    </>}
    {!page && !error && <p role="status" className="mt-4 text-sm">Loading saved drafts…</p>}
    {error && <p role="alert" className="mt-4 text-sm">{error}</p>}
  </section>
}
