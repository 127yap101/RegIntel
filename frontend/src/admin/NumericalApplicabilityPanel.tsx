import { useId, useState } from 'react'
import { Button } from '../components/Button'
import { AdminApi, AdminError } from './api'
import { applicabilityInspected, applicabilityInspectionPhrases, applicabilitySelection } from './numericalApplicability'
import { checked } from './wire'
import type * as T from './generated'

interface Props {
  api: AdminApi
  packet: T.NumericalReviewPacket
  busy: boolean
  locked: boolean
  run: (action: (signal: AbortSignal) => Promise<void>) => Promise<void>
  pendingChanged: (pending: boolean) => void
  inspect: (proof: T.NumericalEvidenceBinding, word: T.BoundNumericalWord) => void
  inspected: readonly string[]
  openResolved: (packet: T.NumericalReviewPacket) => void
}

const labels = { CROSS_PAGE: 'Applies across source pages', BASIS: 'Reporting basis applies to the target value', QUALIFIED_DEFAULT: 'Qualified default applies to the target value' } as const

export function NumericalApplicabilityPanel({ api, packet, busy, locked, run, pendingChanged, inspect, inspected, openResolved }: Props) {
  const [requirements, setRequirements] = useState<T.NumericalApplicabilityRequirements | null>(null)
  const [review, setReview] = useState<T.ReviewedNumericalApplicability | null>(null)
  const [note, setNote] = useState(''); const [confirmed, setConfirmed] = useState(false)
  const [pending, setPending] = useState<T.NumericalApplicabilityRequest | null>(null)
  const [rerunPending, setRerunPending] = useState(false)
  const noteId = useId()
  const complete = requirements !== null && applicabilityInspected(packet, requirements, inspected)

  function retain(value: T.NumericalApplicabilityRequest | null): void { setPending(value); pendingChanged(value !== null) }
  function load(): void {
    if (locked) return
    setRequirements(null); setReview(null); setNote(''); setConfirmed(false)
    void run(async (signal) => {
      const required = await api.numericalApplicabilityRequirements(packet, signal)
      const stored = await api.numericalApplicabilityReview(packet, signal)
      if (!signal.aborted) { setRequirements(required); setReview(stored) }
    })
  }
  function save(): void {
    if (busy || review || !requirements || !pending && (locked || !requirements.eligible || !complete || !confirmed || !note.trim() || note.includes('\0'))) return
    void run(async (signal) => {
      const body = pending ?? checked('numerical_applicability_request', { ...applicabilitySelection(requirements), schema_version: 'numerical-applicability-request-1', decision: 'APPLIES', note })
      retain(body)
      try {
        const stored = await api.reviewNumericalApplicability(packet, requirements, body, signal)
        if (!signal.aborted) { setReview(stored); setNote(''); setConfirmed(false); retain(null) }
      } catch (error: unknown) {
        // A rejected transaction has a known outcome. Keep all uncertain writes
        // frozen until the exact request returns a verified immutable receipt.
        if (!signal.aborted && error instanceof AdminError && (error.status === 409 || error.status === 422)) { retain(null); setRequirements(null); setConfirmed(false) }
        throw error
      }
    })
  }
  function runGate(): void {
    if (busy || !review || locked && !rerunPending) return
    void run(async (signal) => {
      setRerunPending(true); pendingChanged(true)
      try {
        const resolved = await api.runNumericalApplicability(packet, review, signal)
        if (!signal.aborted) { setRerunPending(false); pendingChanged(false); openResolved(resolved) }
      } catch (error: unknown) {
        if (!signal.aborted && error instanceof AdminError && (error.status === 409 || error.status === 422)) { setRerunPending(false); pendingChanged(false); setRequirements(null); setReview(null) }
        throw error
      }
    })
  }

  return <section aria-label="Numerical source applicability review" className="mt-5 border-t border-line pt-4">
    <h4 className="font-semibold">Source applicability</h4>
    <p className="mt-2 text-sm text-muted">Review whether the selected cross-page definitions and qualified statements apply to this exact table value. This attestation does not complete the numerical gates, accept a fact or publish it. Context confirmation, acceptance and publication remain separate.</p>
    <Button className="mt-3" variant="secondary" disabled={locked} onClick={load}>Check applicability requirements and history</Button>
    {pending && <p role="status" className="mt-3 rounded border border-line p-3 text-sm">The applicability review is awaiting a verified response. Its exact source selection and note are locked. Retry the same request to verify the outcome.</p>}
    {rerunPending && <p role="status" className="mt-3 rounded border border-line p-3 text-sm">The numerical gate rerun is awaiting a verified response. Retry the same source and recorded applicability review before starting another operation.</p>}
    {requirements && <>
      <p className="mt-3 text-sm font-semibold">{requirements.eligible ? 'Eligible for an explicit applicability review' : 'Applicability review is blocked'}</p>
      {requirements.blockers.length > 0 && <ul aria-label="Applicability blockers" className="mt-2 list-disc space-y-1 pl-5 text-sm">{requirements.blockers.map((blocker, index) => <li key={index}>{blocker}</li>)}</ul>}
      <p className="mt-2 text-xs text-muted">Selected source pages: {requirements.reviewed_page_indices.map((page) => page + 1).join(', ')}. Page numbers refer to the original PDF.</p>
      <p className="mt-2 text-xs text-muted">Open each target cell and each asserted phrase using its original word buttons. Read the complete words below against the rendered PDF, including qualifiers and surrounding context.</p>
      <ul aria-label="Applicability source selection" className="mt-3 space-y-4">{applicabilityInspectionPhrases(packet, requirements).map((phrase) => {
        const assertions = requirements.assertions.filter((assertion) => assertion.role === phrase.role && assertion.ordinal === phrase.ordinal)
        const cell = packet.binding.cells.find((item) => item.role === phrase.role && phrase.ordinal === 0)
        const opened = phrase.words.some((word) => inspected.includes(word.evidence.id))
        return <li key={`${phrase.role}:${phrase.ordinal}`} className="rounded border border-line p-3">
          <h5 className="text-sm font-semibold">{phrase.role} · {phrase.ordinal + 1}{cell ? ' · Target cell' : ''}</h5>
          {cell && <p className="mt-1 break-all text-xs text-muted">Table {cell.artifact_table_id} · Cell {cell.artifact_cell_id} · Row {cell.row_index + 1}, column {cell.column_index + 1} · Spans {cell.row_span} × {cell.column_span}</p>}
          {assertions.map((assertion) => <p key={assertion.kind} className="mt-2 text-sm">{labels[assertion.kind]} ({assertion.kind})</p>)}
          <div className="mt-2 flex flex-wrap gap-2">{phrase.words.map((word, index) => <button key={word.evidence.id} type="button" disabled={locked} aria-label={`Inspect applicability word ${index + 1} in ${phrase.role} ${phrase.ordinal + 1}`} className="max-w-full rounded border border-line px-2 py-1 text-left text-xs focus-visible:outline-2 focus-visible:outline-sage" onClick={() => inspect(packet.binding, word)}><span className="whitespace-pre-wrap break-all">{word.evidence.span.quote}</span><span className="mt-1 block text-muted">Page {word.evidence.source.page_index + 1}</span></button>)}</div>
          <p className="mt-2 text-xs text-muted">{opened ? 'Verified source page opened for this phrase.' : 'Open this phrase in the verified source viewer before confirming.'}</p>
        </li>
      })}</ul>
      {review ? <div aria-label="Recorded applicability review" className="mt-4 rounded border border-line p-3"><p className="text-sm font-semibold">Recorded applicability decision: {review.request.decision}</p><p className="mt-2 whitespace-pre-wrap break-words text-sm">{review.request.note}</p><p className="mt-2 break-all text-xs text-muted">Review {review.id} · Reviewer {review.reviewed_by}</p><p className="mt-2 text-sm">The stored gate remains {packet.gate.state}. This recorded attestation alone does not complete validation or publish a fact.</p><Button className="mt-3" disabled={busy || locked && !rerunPending} onClick={runGate}>{rerunPending ? 'Retry the same numerical gate rerun' : 'Rerun numerical gates with recorded applicability'}</Button><p className="mt-2 text-xs text-muted">This explicit rerun checks the current source and approvals, then opens its retained gate. It does not submit context confirmation, acceptance or publication.</p></div> : <form className="mt-4 grid gap-3" onSubmit={(event) => { event.preventDefault(); save() }}>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" disabled={locked || !requirements.eligible || !complete} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I inspected all selected source pages and exact phrases and confirm that every listed applicability assertion applies to this target value.</span></label>
        {!complete && <p className="text-xs text-muted">Confirmation remains unavailable until every selected phrase and target cell has a verified rendered source page.</p>}
        <div><label htmlFor={noteId} className="text-sm">Applicability review note</label><textarea id={noteId} required maxLength={2000} disabled={locked || !requirements.eligible} className="admin-input" rows={3} value={note} onChange={(event) => setNote(event.target.value)} /></div>
        <p className="text-xs text-muted">The current signed-in administrator is recorded by the server. All source IDs, pages and assertion words are retained unchanged.</p>
        <Button type="submit" disabled={busy || !pending && (locked || !requirements.eligible || !complete || !confirmed || !note.trim() || note.includes('\0'))}>{pending ? 'Retry the same applicability review' : 'Record applicability review'}</Button>
      </form>}
    </>}
  </section>
}
