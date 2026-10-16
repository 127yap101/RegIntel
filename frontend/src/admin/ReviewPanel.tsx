import { useId, useState } from 'react'
import { Button } from '../components/Button'
import { FinancialContext } from '../published/FinancialContext'
import type * as T from './generated'

export function ReviewPanel({ page, busy, load, inspect, decide, select, revalidate }: {
  page: T.ReviewPage; busy: boolean
  load: (state: T.ReviewFilter, offset: number) => void
  inspect: (item: T.ReviewItem, span: T.SourceSpan) => void
  decide: (item: T.ReviewItem, decision: T.ReviewDecision['decision'], note: string) => void
  select: (item: T.ReviewItem) => void
  revalidate: () => void
}) {
  const stateId = useId()
  return <section aria-label="Candidate review" className="mt-5 space-y-5">
    <h3 className="text-lg font-semibold">Review candidate disclosures</h3>
    <p className="break-all text-xs text-muted">Validation {page.run_id} · parse {page.parse_version_id}</p>
    <p className="text-sm leading-6">A recorded approval makes a candidate eligible for a separate publication. Failed or unresolved mandatory checks cannot be overridden.</p>
    {!page.approval_current && <p role="status" className="rounded border border-amber p-3 text-sm">This audit uses an older configuration or source decision. Run validation again before approving new decisions.</p>}
    <div><label htmlFor={stateId} className="block text-sm font-medium">Candidate state</label><select id={stateId} value={page.state_filter} disabled={busy} onChange={(event) => { const value = event.target.value; if (value === 'ALL' || value === 'PASS' || value === 'REVIEW' || value === 'QUARANTINED') load(value, 0) }} className="ml-3 rounded border border-line p-2"><option>ALL</option><option>QUARANTINED</option><option>REVIEW</option><option>PASS</option></select><Button className="mt-3" variant="secondary" disabled={busy} onClick={revalidate}>Run current validation</Button></div>
    {!page.items.length && <p role="status" className="text-sm">No candidates match this page and filter.</p>}
    {page.items.map((item) => <ReviewCard key={`${item.candidate.id}:${item.review?.id ?? 'open'}`} item={item} busy={busy} current={page.approval_current} inspect={(span) => inspect(item, span)} decide={(decision, note) => decide(item, decision, note)} select={() => select(item)} />)}
    <div className="flex flex-wrap gap-3"><Button variant="secondary" disabled={busy || page.offset === 0} onClick={() => load(page.state_filter, Math.max(0, page.offset - page.limit))}>Previous candidates</Button><Button variant="secondary" disabled={busy || !page.has_more} onClick={() => load(page.state_filter, page.offset + page.limit)}>More candidates</Button></div>
  </section>
}

function ReviewCard({ item, busy, current, inspect, decide, select }: { item: T.ReviewItem; busy: boolean; current: boolean; inspect: (span: T.SourceSpan) => void; decide: (decision: T.ReviewDecision['decision'], note: string) => void; select: () => void }) {
  const eligible = item.result.reviewer_eligible && current
  const [note, setNote] = useState('')
  const noteId = useId()
  const [decision, setDecision] = useState<T.ReviewDecision['decision']>(eligible ? 'APPROVE_FOR_PUBLICATION' : 'REJECT')
  const spans = [...item.draft.supports.map((span) => ({ role: 'Disclosure', span })), ...item.result.context_supports.map((witness) => ({ role: witness.role, span: witness.span }))]
  return <article className="rounded-xl border border-line bg-white p-4 sm:p-5" aria-label={`Candidate ${item.candidate.id}`}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="font-semibold">{item.metric_label ?? item.candidate.relation_type ?? item.candidate.kind}</h4><span className="rounded bg-paper px-3 py-1 text-xs font-semibold">{item.result.state}</span></div>
    <blockquote className="mt-3 whitespace-pre-wrap break-words text-sm leading-7">{item.draft.raw_text}</blockquote>
    <dl className="mt-3 space-y-2 break-all text-xs text-muted"><div><dt>Candidate</dt><dd>{item.candidate.id}</dd></div><div><dt>Subject → object</dt><dd>{item.candidate.subject_entity_id} → {item.candidate.object_entity_id ?? 'No object (fact)'}</dd></div></dl>
    <FinancialContext quantity={item.result.quantity} />
    <details className="mt-4"><summary className="cursor-pointer text-sm font-semibold">All 16 validation checks</summary><ul className="mt-3 space-y-2">{item.result.checks.map((check) => <li key={check.code} className="text-xs leading-6"><strong>{check.code} · {check.state}</strong> — {check.message}</li>)}</ul></details>
    <details className="mt-4" open><summary className="cursor-pointer text-sm font-semibold">Exact source support</summary><ul className="mt-3 space-y-4">{spans.map(({ span, role }, index) => <li key={`${role}:${index}`} className="border-l-2 border-sage pl-3"><p className="text-xs text-muted">{role} · characters {span.start}–{span.end}</p><blockquote className="mt-1 whitespace-pre-wrap break-words text-sm leading-6">{span.quote}</blockquote><Button className="mt-2" variant="secondary" disabled={busy} onClick={() => inspect(span)}>Inspect source {index + 1}</Button></li>)}</ul></details>
    {item.accepted_observation_id && <p className="mt-4 break-all text-sm">Already accepted as observation {item.accepted_observation_id}. Published history is preserved through the parent corpus.</p>}
    {item.review ? <div className="mt-4 rounded border border-line bg-paper p-3"><p className="text-sm font-semibold">Recorded decision: {item.review.decision}</p><p className="mt-2 whitespace-pre-wrap break-words text-sm">{item.review.review_note}</p><p className="mt-2 break-all text-xs text-muted">Review {item.review.id} · audit {item.review.validation_run_id}. This final decision is immutable.</p>{item.review.decision === 'APPROVE_FOR_PUBLICATION' && !item.accepted_observation_id && <Button className="mt-3" variant="secondary" disabled={busy} onClick={select}>Add reviewed candidate to draft</Button>}</div> : <form className="mt-5 space-y-3" onSubmit={(event) => { event.preventDefault(); if (note.trim() && (decision === 'REJECT' || eligible)) decide(decision, note) }}>
      <div><label htmlFor={noteId + '-decision'} className="block text-sm font-medium">Review decision</label><select id={noteId + '-decision'} value={decision} disabled={busy} onChange={(event) => { if (event.target.value === 'REJECT' || event.target.value === 'APPROVE_FOR_PUBLICATION') setDecision(event.target.value) }} className="mt-2 block max-w-full rounded border border-line p-2"><option value="APPROVE_FOR_PUBLICATION" disabled={!eligible}>Approve for a publication draft</option><option value="REJECT">Reject candidate</option></select></div>
      <div><label htmlFor={noteId} className="block text-sm font-medium">Decision note</label><textarea id={noteId} required maxLength={2000} rows={3} value={note} onChange={(event) => setNote(event.target.value)} className="mt-2 block w-full rounded border border-line p-3" /></div>
      {!eligible && <p className="text-xs text-muted">Approval is unavailable until every required gate is resolved in a current audit.</p>}
      <Button type="submit" disabled={busy || !note.trim() || (decision === 'APPROVE_FOR_PUBLICATION' && !eligible)}>Record decision</Button>
    </form>}
  </article>
}
