import { useId, useState } from 'react'
import { Button } from '../components/Button'
import type { AdminApi } from './api'
import type * as T from './generated'

interface Props {
  api: AdminApi
  locked: boolean
  run: (action: (signal: AbortSignal) => Promise<void>) => Promise<void>
  invalidate: () => void
  open: (item: T.NumericalGateQueueItem) => void
}

export function NumericalQueue({ api, locked, run, invalidate, open }: Props) {
  const [state, setState] = useState<T.NumericalGateQueueRequest['state']>('ALL')
  const [review, setReview] = useState<T.NumericalGateQueueRequest['review']>('UNREVIEWED')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState<T.NumericalGateQueuePage | null>(null)
  const stateId = useId(); const reviewId = useId(); const queryId = useId()
  function clear(): void { setPage(null); invalidate() }
  function load(offset = 0): void {
    clear()
    void run(async (signal) => {
      const value = await api.numericalQueue({ state, review, query: query.trim(), offset, limit: 20 }, signal)
      if (!signal.aborted) setPage(value)
    })
  }
  return <section aria-label="Stored numerical checks" className="mt-4 min-w-0 rounded border border-line p-4">
    <h4 className="font-semibold">Find stored numerical checks</h4>
    <p className="mt-2 text-xs text-muted">Search this installation’s uploaded company labels. These are stored inspections and recorded context decisions. Open a check to inspect its full source before reviewing; listing it does not accept or publish a fact.</p>
    <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); load() }}>
      <div><label htmlFor={queryId} className="text-sm">Uploaded company name contains</label><input id={queryId} disabled={locked} maxLength={120} className="admin-input" value={query} onChange={(event) => { clear(); setQuery(event.target.value) }} /></div>
      <div><label htmlFor={stateId} className="text-sm">Stored numerical check status</label><select id={stateId} disabled={locked} className="admin-input" value={state} onChange={(event) => { clear(); setState(event.target.value as typeof state) }}><option value="ALL">All check states</option><option value="READY_FOR_REVIEW">Ready for review</option><option value="REVIEW_REQUIRED">Needs context resolution</option><option value="QUARANTINED">Quarantined</option></select></div>
      <div><label htmlFor={reviewId} className="text-sm">Recorded numerical context review</label><select id={reviewId} disabled={locked} className="admin-input" value={review} onChange={(event) => { clear(); setReview(event.target.value as typeof review) }}><option value="UNREVIEWED">Unreviewed</option><option value="ALL">All recorded review states</option><option value="CONFIRM_CONTEXT">Context confirmed</option><option value="REJECT">Context rejected</option></select></div>
      <Button type="submit" disabled={locked} className="self-end">Find numerical checks</Button>
    </form>
    {page && <><p className="mt-3 text-xs text-muted">Stored results are ordered by gate ID. Check and review records can change as you work; refresh to reload this queue page.</p>
      <ul className="mt-3 space-y-3">{page.items.map((item) => <li key={item.gate.id} className="min-w-0 rounded border border-line p-3 text-sm"><p className="whitespace-pre-wrap break-words font-semibold">{item.company_name_raw} · {item.document_type}</p><p className="mt-1">Stored check: {item.gate.state} · Recorded review: {item.review?.request.decision ?? 'UNREVIEWED'}</p>{item.gate.quantity_proposal && <p className="mt-1 break-words text-xs">Proposed raw value: {item.gate.quantity_proposal.raw_value} · Period end: {item.gate.quantity_proposal.period.end_date ?? 'Unknown'}</p>}<p className="mt-1 break-all text-xs text-muted">Gate {item.gate.id} · Filing version {item.filing_version_id}</p><Button className="mt-2" variant="secondary" disabled={locked} aria-label={`Open numerical check ${item.gate.id}`} onClick={() => open(item)}>Open stored check</Button></li>)}</ul>
      {!page.items.length && <p role="status" className="mt-3 text-sm">No stored numerical checks match these filters on this page. Source intake and gate creation must happen before review.</p>}
      <div className="mt-3 flex flex-wrap gap-3"><Button variant="secondary" disabled={locked} onClick={() => load(page.offset)}>Refresh numerical checks</Button><Button variant="secondary" disabled={locked || page.offset === 0} onClick={() => load(Math.max(0, page.offset - page.limit))}>Previous numerical checks</Button><Button variant="secondary" disabled={locked || !page.has_more || page.offset + page.limit > 10000} onClick={() => load(page.offset + page.limit)}>More numerical checks</Button></div>
      {page.has_more && page.offset + page.limit > 10000 && <p role="status" className="mt-2 text-sm">Narrow the company or status filters to inspect further results.</p>}
    </>}
  </section>
}
