import { useId, useState } from 'react'
import { Button } from '../components/Button'
import { AdminApi, AdminError } from './api'
import { canonical, checked } from './wire'
import type * as T from './generated'

type PendingDecision =
  | { kind: 'context'; body: T.NumericalContextReviewRequest }
  | { kind: 'candidate'; body: T.NumericalCandidateRequest; preparation: T.NumericalPublicationPreparation }
  | { kind: 'acceptance'; body: T.NumericalAcceptanceRequest; candidate: T.StoredNumericalCandidate }

interface Props {
  api: AdminApi
  busy: boolean
  run: (action: (signal: AbortSignal) => Promise<void>) => Promise<void>
  pendingChanged: (pending: boolean) => void
  clearSource: () => void
  inspect: (proof: T.NumericalEvidenceBinding, word: T.BoundNumericalWord) => void
  select: (accepted: T.StoredNumericalAcceptance) => void
}

function Checks({ checks, label }: { checks: readonly { code: string; state: string; message: string }[]; label: string }) {
  return <details className="mt-3 rounded border border-line p-3"><summary className="cursor-pointer text-sm font-semibold">{label}</summary><ul className="mt-3 space-y-2 text-xs">{checks.map((check) => <li key={check.code}><strong>{check.code} · {check.state}</strong><p className="mt-1 whitespace-pre-wrap break-words">{check.message}</p></li>)}</ul></details>
}

function ProposedQuantity({ quantity }: { quantity: T.NumericalQuantityProposal }) {
  return <dl aria-label="Proposed numerical context" className="mt-3 grid gap-2 break-words text-sm sm:grid-cols-2"><div><dt className="text-muted">Raw value</dt><dd>{quantity.raw_value}</dd></div><div><dt className="text-muted">Normalized value</dt><dd>{quantity.normalized_value}</dd></div><div><dt className="text-muted">Unit and currency</dt><dd>{quantity.normalized_unit ?? 'Unknown unit'} · {quantity.currency ?? 'Unknown currency'}</dd></div><div><dt className="text-muted">Reporting basis</dt><dd>{quantity.basis}</dd></div><div className="sm:col-span-2"><dt className="text-muted">Financial period</dt><dd>{quantity.period.kind} · {quantity.period.start_date ?? 'Unknown start'} to {quantity.period.end_date ?? 'Unknown end'}</dd></div></dl>
}

export function NumericalPanel({ api, busy, run, pendingChanged, clearSource, inspect, select }: Props) {
  const [gateId, setGateId] = useState(''); const [candidateId, setCandidateId] = useState('')
  const [packet, setPacket] = useState<T.NumericalReviewPacket | null>(null)
  const [preparation, setPreparation] = useState<T.NumericalPublicationPreparation | null>(null)
  const [candidate, setCandidate] = useState<T.StoredNumericalCandidate | null>(null)
  const [acceptance, setAcceptance] = useState<T.StoredNumericalAcceptance | null>(null)
  const [contextDecision, setContextDecision] = useState<T.NumericalContextReviewRequest['decision']>('REJECT')
  const [acceptDecision, setAcceptDecision] = useState<T.NumericalAcceptanceRequest['decision']>('REJECT')
  const [contextNote, setContextNote] = useState(''); const [acceptNote, setAcceptNote] = useState('')
  const [pending, setPending] = useState<PendingDecision | null>(null)
  const contextNoteId = useId(); const acceptNoteId = useId(); const contextDecisionId = useId(); const acceptDecisionId = useId()
  const locked = busy || pending !== null

  function retain(value: PendingDecision | null): void { setPending(value); pendingChanged(value !== null) }
  async function submitWrite(action: () => Promise<void>, signal: AbortSignal): Promise<void> {
    try { await action() }
    catch (error: unknown) {
      // Explicit transaction/validation rejection has a known outcome. Transport,
      // unavailable storage and unverifiable responses keep the exact write frozen.
      if (!signal.aborted && error instanceof AdminError && (error.status === 409 || error.status === 422)) { retain(null); setPreparation(null) }
      throw error
    }
  }
  function clearLoaded(): void { setPacket(null); setPreparation(null); setCandidate(null); setAcceptance(null); setContextNote(''); setAcceptNote(''); clearSource() }
  function load(): void {
    clearLoaded()
    void run(async (signal) => {
      const loaded = await api.numericalPacket(canonical(gateId.trim()), signal)
      const restored = candidateId.trim() ? await api.numericalCandidate(loaded, canonical(candidateId.trim()), signal) : null
      const decision = restored ? await api.numericalAcceptance(restored, signal) : null
      if (!signal.aborted) { setPacket(loaded); setCandidate(restored); setPreparation(restored?.preparation ?? null); setAcceptance(decision) }
    })
  }
  function reviewContext(): void {
    if (!packet || packet.review) return
    void run(async (signal) => {
      const saved = pending?.kind === 'context' ? pending : { kind: 'context' as const, body: checked('numerical_review_request', { gate_run_id: packet.gate.id, decision: contextDecision, evidence_ids: packet.gate.evidence_ids, note: contextNote }) }
      retain(saved)
      await submitWrite(async () => { const review = await api.reviewNumerical(packet, saved.body, signal); if (!signal.aborted) { setPacket({ ...packet, review }); setPreparation(null); retain(null); setContextNote('') } }, signal)
    })
  }
  function prepare(): void {
    if (!packet) return; setPreparation(null)
    void run(async (signal) => { const value = await api.numericalPreparation(packet, signal); if (!signal.aborted) setPreparation(value) })
  }
  function createCandidate(): void {
    if (!packet || !preparation?.proposed_input || candidate) return
    void run(async (signal) => {
      const saved = pending?.kind === 'candidate' ? pending : { kind: 'candidate' as const, preparation, body: checked('numerical_candidate_request', { gate_run_id: packet.gate.id, prepared_input_id: preparation.proposed_input?.id }) }
      retain(saved)
      await submitWrite(async () => {
        const value = await api.createNumericalCandidate(packet, saved.preparation, saved.body, signal)
        const decision = await api.numericalAcceptance(value, signal)
        if (!signal.aborted) { setCandidate(value); setCandidateId(value.record.id); setAcceptance(decision); retain(null) }
      }, signal)
    })
  }
  function decideCandidate(): void {
    if (!candidate || !packet || acceptance) return
    void run(async (signal) => {
      const saved = pending?.kind === 'acceptance' ? pending : { kind: 'acceptance' as const, candidate, body: checked('numerical_acceptance_request', { candidate_id: candidate.record.id, decision: acceptDecision, evidence_ids: packet.gate.evidence_ids, note: acceptNote }) }
      retain(saved)
      await submitWrite(async () => { const value = await api.decideNumerical(saved.candidate, saved.body, signal); if (!signal.aborted) { setAcceptance(value); retain(null); setAcceptNote('') } }, signal)
    })
  }

  return <section aria-label="Numerical filing review" className="mt-5 min-w-0 rounded-xl border border-line bg-white p-5">
    <h3 className="text-xl font-semibold">Numerical filings</h3>
    <p className="mt-2 text-sm text-muted">Inspect exact source context, record separate review decisions, then select an accepted candidate for the publication draft below.</p>
    <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); load() }}>
      <label className="text-sm">Saved numerical gate ID<input required disabled={locked} value={gateId} onChange={(event) => { clearLoaded(); setGateId(event.target.value) }} className="admin-input" spellCheck={false} /></label>
      <label className="text-sm">Saved numerical candidate ID (optional)<input disabled={locked} value={candidateId} onChange={(event) => { clearLoaded(); setCandidateId(event.target.value) }} className="admin-input" spellCheck={false} /></label>
      <p className="text-xs text-muted sm:col-span-2">Use the IDs from this installation’s source-intake workflow. Include a candidate ID to restore its recorded decision.</p>
      <Button type="submit" disabled={locked || !gateId.trim()}>Load numerical review</Button>
    </form>
    {pending && <p role="status" className="mt-4 rounded border border-line p-3 text-sm">The submitted {pending.kind} write is awaiting a verified response. Its fields are locked; retry the same request below. Save the displayed IDs before signing out.</p>}
    {packet && <>
      <div className="mt-5 border-t border-line pt-4"><h4 className="font-semibold">Stored gate: {packet.gate.state}</h4><p className="mt-2 break-all text-xs text-muted">Gate {packet.gate.id} · Parse {packet.gate.parse_version_id}</p><p className="mt-1 break-all text-xs text-muted">Original PDF SHA-256: {packet.binding.source_sha256}</p><p className="mt-2 text-xs text-muted">This is a retained inspection. Candidate acceptance and publication recheck current prerequisites.</p></div>
      {packet.gate.quantity_proposal && <ProposedQuantity quantity={packet.gate.quantity_proposal} />}
      <Checks checks={packet.gate.checks} label="All 14 source and context gates" />
      <details className="mt-3 rounded border border-line p-3"><summary className="cursor-pointer text-sm font-semibold">Original source words and table context</summary><p className="mt-3 text-xs text-muted">Each button retains one separate original word span, in source order. Open it to inspect the verified PDF page.</p><ul className="mt-3 space-y-4">{packet.binding.phrases.map((phrase) => {
        const cell = packet.binding.cells.find((value) => value.role === phrase.role && phrase.ordinal === 0)
        return <li key={`${phrase.role}:${phrase.ordinal}`}><h5 className="text-sm font-semibold">{phrase.role} · {phrase.ordinal + 1}</h5>{cell && <p className="mt-1 break-all text-xs text-muted">Table {cell.artifact_table_id} · Cell {cell.artifact_cell_id} · Row {cell.row_index + 1}, column {cell.column_index + 1} · Spans {cell.row_span} × {cell.column_span}</p>}<div className="mt-2 flex flex-wrap gap-2">{phrase.words.map((word, index) => <button key={`${word.evidence.id}:${index}`} type="button" disabled={busy} aria-label={`Inspect original word ${index + 1} in ${phrase.role} ${phrase.ordinal + 1}`} className="max-w-full rounded border border-line px-2 py-1 text-left text-xs focus-visible:outline-2 focus-visible:outline-sage" onClick={() => inspect(packet.binding, word)}><span className="whitespace-pre-wrap break-all">{word.evidence.span.quote}</span><span className="mt-1 block text-muted">Page {word.evidence.source.page_index + 1}</span></button>)}</div></li>
      })}</ul></details>
      <section aria-label="Numerical context review" className="mt-5 border-t border-line pt-4"><h4 className="font-semibold">Context review</h4>
        {packet.review ? <><p className="mt-2 text-sm">Recorded context decision: {packet.review.request.decision}</p><p className="mt-1 whitespace-pre-wrap break-words text-sm">{packet.review.request.note}</p><p className="mt-1 break-all text-xs text-muted">Review {packet.review.id} · Reviewer {packet.review.reviewed_by}</p></> : <form className="mt-3 grid gap-3" onSubmit={(event) => { event.preventDefault(); reviewContext() }}><div><label htmlFor={contextDecisionId} className="text-sm">Numerical context decision</label><select id={contextDecisionId} disabled={locked} className="admin-input" value={contextDecision} onChange={(event) => setContextDecision(event.target.value as typeof contextDecision)}><option value="REJECT">Reject context</option><option value="CONFIRM_CONTEXT" disabled={packet.gate.state !== 'READY_FOR_REVIEW'}>Confirm complete source context</option></select></div><div><label htmlFor={contextNoteId} className="text-sm">Context review note</label><textarea id={contextNoteId} required maxLength={2000} disabled={locked} className="admin-input" rows={3} value={contextNote} onChange={(event) => setContextNote(event.target.value)} /></div><Button type="submit" disabled={busy || pending !== null && pending.kind !== 'context' || pending === null && (!contextNote.trim() || contextNote.includes('\0') || packet.gate.evidence_ids.length === 0)}>{pending?.kind === 'context' ? 'Retry the same context decision' : 'Record context decision'}</Button></form>}
      </section>
      {packet.review?.request.decision === 'CONFIRM_CONTEXT' && <section aria-label="Numerical candidate preparation" className="mt-5 border-t border-line pt-4"><h4 className="font-semibold">Candidate prerequisites</h4><p className="mt-2 text-xs text-muted">Creating a candidate stores the checked proposal. Acceptance and publication remain separate actions.</p>{!candidate && <Button className="mt-3" variant="secondary" disabled={locked} onClick={prepare}>Check current candidate prerequisites</Button>}{preparation && <><p className="mt-3 text-sm">{candidate ? 'Stored preparation snapshot' : 'Current preparation'}: {preparation.state}</p>{preparation.proposed_input && <p className="mt-1 break-all text-xs text-muted">Metric: {preparation.proposed_input.metric.label} · Subject {preparation.proposed_input.subject_entity_id}</p>}<Checks checks={preparation.checks} label="All 16 candidate validation checks" />{!candidate && preparation.state === 'READY_FOR_ADAPTER' && <Button className="mt-3" disabled={busy || pending !== null && pending.kind !== 'candidate'} onClick={createCandidate}>{pending?.kind === 'candidate' ? 'Retry the same candidate request' : 'Save numerical candidate'}</Button>}</>}</section>}
      {candidate && <section aria-label="Numerical candidate acceptance" className="mt-5 border-t border-line pt-4"><h4 className="font-semibold">Candidate acceptance</h4><p className="mt-2 break-all text-xs text-muted">Candidate {candidate.record.id}</p>
        {acceptance ? <><p className="mt-2 text-sm">Recorded numerical decision: {acceptance.record.request.decision}</p><p className="mt-1 whitespace-pre-wrap break-words text-sm">{acceptance.record.request.note}</p><p className="mt-1 break-all text-xs text-muted">Decision {acceptance.record.id} · Reviewer {acceptance.record.reviewed_by}</p><p className="mt-2 text-xs text-muted">This immutable decision records its acceptance step. The publication build separately checks current eligibility and corpus membership.</p>{acceptance.record.state === 'ACCEPTED_UNPUBLISHED' && <Button className="mt-3" disabled={locked} onClick={() => select(acceptance)}>Add accepted numerical candidate to draft</Button>}</> : <form className="mt-3 grid gap-3" onSubmit={(event) => { event.preventDefault(); decideCandidate() }}><div><label htmlFor={acceptDecisionId} className="text-sm">Numerical acceptance decision</label><select id={acceptDecisionId} className="admin-input" disabled={locked} value={acceptDecision} onChange={(event) => setAcceptDecision(event.target.value as typeof acceptDecision)}><option value="REJECT">Reject candidate</option><option value="ACCEPT">Accept after current mandatory checks</option></select></div><div><label htmlFor={acceptNoteId} className="text-sm">Numerical acceptance note</label><textarea id={acceptNoteId} required maxLength={2000} disabled={locked} className="admin-input" rows={3} value={acceptNote} onChange={(event) => setAcceptNote(event.target.value)} /></div><Button type="submit" disabled={busy || pending !== null && pending.kind !== 'acceptance' || pending === null && (!acceptNote.trim() || acceptNote.includes('\0'))}>{pending?.kind === 'acceptance' ? 'Retry the same acceptance decision' : 'Record numerical acceptance decision'}</Button></form>}
      </section>}
    </>}
  </section>
}
