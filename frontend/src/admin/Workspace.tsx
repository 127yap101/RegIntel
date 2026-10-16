import { useEffect, useRef, useState } from 'react'
import { Button } from '../components/Button'
import { SourceViewer } from '../published/SourceViewer'
import { AdminApi, AdminError } from './api'
import { checked, PendingWrites, sameValue } from './wire'
import { UploadForm, FilingPanel, ProcessingPanel } from './JobsPanel'
import { ReviewPanel } from './ReviewPanel'
import { BuildPanel, PublicationForm } from './PublicationPanel'
import type * as T from './generated'

const queues: readonly { kind: T.QueueKind; label: string }[] = [{ kind: 'filings', label: 'Filing jobs' }, { kind: 'processing', label: 'Processing jobs' }, { kind: 'validations', label: 'Validation and quarantine' }, { kind: 'publications', label: 'Publication builds' }]
interface SourceSelection { evidence: T.EvidenceData; supports: readonly T.SourceSpan[]; context_supports: readonly T.ContextWitness[]; bytes: Uint8Array<ArrayBuffer> }

export function AdminWorkspace() {
  const [api, setApi] = useState<AdminApi | null>(null)
  const [username, setUsername] = useState(''); const [password, setPassword] = useState('')
  const [queue, setQueue] = useState<T.QueuePage | null>(null)
  const [filing, setFiling] = useState<T.FilingJob | null>(null); const [processing, setProcessing] = useState<T.ProcessingJob | null>(null)
  const [reviews, setReviews] = useState<T.ReviewPage | null>(null); const [metrics, setMetrics] = useState<readonly T.MetricDefinition[] | null>(null)
  const [manifest, setManifest] = useState<T.CorpusManifest | null>(null); const [published, setPublished] = useState(false)
  const [selections, setSelections] = useState<readonly T.CandidateSelection[]>([])
  const [source, setSource] = useState<SourceSelection | null>(null)
  const [head, setHead] = useState<string | null>(null); const [draftNumber, setDraftNumber] = useState(0)
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState('')
  const operation = useRef<AbortController | null>(null)
  const pending = useRef(new PendingWrites())
  useEffect(() => () => { operation.current?.abort(); pending.current.clear() }, [])

  function clearSelection(): void { setFiling(null); setProcessing(null); setReviews(null); setManifest(null); setPublished(false); setSource(null); setMetrics(null) }
  function clearPrivate(): void { setApi(null); setQueue(null); clearSelection(); setSelections([]); setHead(null); setUsername(''); setPassword(''); setDraftNumber((previous) => previous + 1); pending.current.clear() }
  function logout(): void { operation.current?.abort(); clearPrivate(); setBusy(false); setMessage('Administrator signed out.') }
  async function execute(action: (signal: AbortSignal) => Promise<void>): Promise<void> {
    operation.current?.abort(); const controller = new AbortController(); operation.current = controller
    setBusy(true); setMessage('')
    try { await action(controller.signal) }
    catch (error: unknown) { if (controller.signal.aborted) return; if (error instanceof AdminError && error.auth) clearPrivate(); setMessage(error instanceof AdminError ? error.message : 'The source or request could not be verified. Check the fields and refresh the stored state.') }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }
  async function signIn(): Promise<void> {
    const submitted = password; setPassword('')
    await execute(async (signal) => { const client = await AdminApi.login(username, submitted, signal); const result = await client.queue('filings', 0, signal); if (!signal.aborted) { setApi(client); setQueue(result); setHead(result.published_corpus_id) } })
  }
  async function loadQueue(kind: T.QueueKind, offset = 0): Promise<void> {
    if (!api) return; clearSelection(); setQueue(null)
    await execute(async (signal) => { const result = await api.queue(kind, offset, signal); if (!signal.aborted) { setQueue(result); setHead(result.published_corpus_id) } })
  }
  async function reviewRun(id: string, filter: T.ReviewFilter = 'ALL', offset = 0): Promise<void> {
    if (!api) return; clearSelection()
    await execute(async (signal) => { const result = await api.reviews(id, filter, offset, signal); if (!signal.aborted) setReviews(result) })
  }
  async function choose(item: T.QueueItem): Promise<void> {
    if (!api || !queue) return
    const kind = queue.kind; clearSelection()
    if (kind === 'validations') { await reviewRun(item.id); return }
    await execute(async (signal) => {
      if (kind === 'filings') { const job = await api.filing(item.id, signal); const catalog = await api.read('metrics', '/v1/admin/workspace/metrics', signal); if (!signal.aborted) { setFiling(job); setMetrics(catalog.items) } }
      else if (kind === 'processing') { const job = await api.processing(item.id, signal); if (!signal.aborted) setProcessing(job) }
      else { const build = await api.build(item.id, signal); if (!signal.aborted) { setManifest(build); setPublished(item.state === 'PUBLISHED') } }
    })
  }
  async function inspect(span: T.SourceSpan, parse: string, contexts: readonly T.ContextWitness[], supports: readonly T.SourceSpan[]): Promise<void> {
    if (!api) return; setSource(null)
    await execute(async (signal) => { const result = await api.source(span, parse, signal); if (!signal.aborted) setSource({ ...result, supports: supports.filter((value) => value.evidence_id === span.evidence_id), context_supports: contexts.filter((value) => value.span.evidence_id === span.evidence_id) }) })
  }
  async function saveReview(item: T.ReviewItem, decision: T.ReviewDecision['decision'], note: string): Promise<void> {
    if (!api || !reviews || item.review || (decision === 'APPROVE_FOR_PUBLICATION' && (!reviews.approval_current || !item.result.reviewer_eligible))) return
    const selected = reviews; setSource(null)
    await execute(async (signal) => {
      const body = pending.current.body('review_request', { candidate_id: item.candidate.id, validation_run_id: selected.run_id, decision, review_note: note, supports: [item.draft.supports[0]] }, 'id')
      const receipt = await api.read('review_receipt', '/v1/admin/validation/reviews', signal, body)
      if (receipt.review_id !== body.id) throw new AdminError(false)
      const page = await api.reviews(selected.run_id, selected.state_filter, selected.offset, signal)
      if (!signal.aborted) { setReviews(page); setMessage('Decision recorded. Publication remains a separate action.') }
    })
  }
  async function validateCandidates(id: string): Promise<void> {
    if (!api) return; setSource(null)
    await execute(async (signal) => { const body = checked('validation_request', { candidate_run_id: id }); const result = await api.read('validation', '/v1/admin/validation/runs', signal, body); if (result.run.candidate_run_id !== id) throw new AdminError(false); const page = await api.reviews(result.run.id, 'ALL', 0, signal); if (!signal.aborted) { clearSelection(); setReviews(page) } })
  }
  async function startProcessing(ids: readonly T.MetricDefinition['id'][]): Promise<void> {
    if (!api || !filing?.parse_version_id) return
    const parse = filing.parse_version_id
    await execute(async (signal) => { const body = pending.current.body('processing_request', { parse_version_id: parse, metric_ids: [...ids].sort() }, 'idempotency_key'); const job = await api.read('processing_job', '/v1/admin/processing/jobs', signal, body); if (job.request.idempotency_key !== body.idempotency_key || job.request.parse_version_id !== parse) throw new AdminError(false); if (!signal.aborted) { clearSelection(); setProcessing(job); setMessage('Workflow submitted. Refresh its stored progress; parsing and extraction require the configured private worker.') } })
  }
  async function upload(file: File, metadata: unknown): Promise<void> {
    if (!api) return
    await execute(async (signal) => { const job = await api.upload(file, metadata, signal); if (!signal.aborted) { clearSelection(); setFiling(job); setMessage('PDF submitted durably. Refresh the filing state to check parsing progress.') } })
  }
  async function createDraft(payload: object): Promise<void> {
    if (!api) return; setManifest(null); setSource(null); setPublished(false)
    await execute(async (signal) => { const body = pending.current.body('publication_request', payload, 'idempotency_key'); const result = await api.read('manifest', '/v1/admin/publication/builds', signal, body); if (result.parent_corpus_version_id !== body.parent_corpus_version_id || result.new_acceptances.some((accepted) => !body.selections.some((selected) => selected.candidate_id === accepted.observation.candidate_id && selected.review_id === accepted.observation.review_id && (selected.review_id === null || accepted.original_review?.decision.id === selected.review_id))) || result.new_acceptances.map((item) => item.observation.candidate_id).sort().join(',') !== body.selections.map((item) => item.candidate_id).sort().join(',') || (body.lineages ?? []).some((item) => !result.lineages.some((stored) => sameValue(stored.proposal, item))) || (body.effects ?? []).some((item) => !result.effects.some((stored) => sameValue(stored.proposal, item)))) throw new AdminError(false); if (!signal.aborted) { setManifest(result); setMessage('Draft checked. Inspect its exact scope and source support before publishing.') } })
  }
  async function publishBuild(operation: 'publish' | 'rebuild'): Promise<void> {
    if (!api || !manifest) return; const id = manifest.id; setSource(null)
    await execute(async (signal) => { const result = await api.build(id, signal, operation); if (!sameValue(result, manifest)) throw new AdminError(false, 'The approved build changed; refresh before publishing.'); if (!signal.aborted) { setManifest(result); setPublished(true); if (operation === 'publish') setHead(id); setMessage(operation === 'publish' ? 'Corpus published. PostgreSQL is authoritative; history is preserved.' : 'Published projections rebuilt from the approved corpus.') } })
  }
  function addSelection(item: T.ReviewItem): void {
    if (!reviews || item.review?.decision !== 'APPROVE_FOR_PUBLICATION' || item.accepted_observation_id) return
    if (!selections.some((selection) => selection.candidate_id === item.candidate.id)) setSelections([...selections, { candidate_id: item.candidate.id, candidate_run_id: reviews.candidate_run_id, review_id: item.review.id }])
    setManifest(null); setSource(null); setMessage('Reviewed candidate added to the publication draft below.')
  }
  return <section id="admin-workspace" aria-label="Administrator workspace" className="scroll-mt-6 pb-12">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-2xl font-semibold">Administrator workspace</h2><p className="mt-2 text-sm text-muted">Filing jobs, exact evidence, audited decisions and explicit publication.</p></div>{api && <Button variant="secondary" onClick={logout}>Sign out of administrator workspace</Button>}</div>
    {!api ? <form className="mt-5 grid gap-4 rounded-xl border border-line bg-white p-5 sm:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => { event.preventDefault(); void signIn() }}><label className="text-sm font-medium">Administrator username<input required autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} className="admin-input" /></label><label className="text-sm font-medium">Administrator password<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} className="admin-input" /></label><Button className="self-end" type="submit" disabled={busy}>Sign in as administrator</Button></form> : <>
      <nav aria-label="Administrator work queues" className="mt-5 flex flex-wrap gap-2">{queues.map(({ kind, label }) => <Button key={kind} variant={queue?.kind === kind ? 'primary' : 'secondary'} disabled={busy} onClick={() => { void loadQueue(kind) }}>{label}</Button>)}</nav>
      {queue && <section aria-label="Selected work queue" className="mt-5 rounded-xl border border-line bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">{queues.find((item) => item.kind === queue.kind)?.label}</h3><Button variant="secondary" disabled={busy} onClick={() => { void loadQueue(queue.kind, queue.offset) }}>Refresh queue</Button></div><p className="mt-2 text-xs text-muted">Ordered by stable identifier. Select an item to inspect its stored state.</p><ul className="mt-4 space-y-3">{queue.items.map((item) => <li key={item.id}><button type="button" disabled={busy} onClick={() => { void choose(item) }} className="w-full rounded-lg border border-line p-3 text-left focus-visible:outline-2 focus-visible:outline-sage"><span className="text-sm font-semibold">{item.label} · {item.state}</span><span className="mt-1 block break-all text-xs text-muted">{item.id}</span></button></li>)}</ul>{!queue.items.length && <p role="status" className="mt-3 text-sm">No items on this queue page. No published corpus is required to upload and review filings.</p>}<div className="mt-4 flex flex-wrap gap-3"><Button variant="secondary" disabled={busy || queue.offset === 0} onClick={() => { void loadQueue(queue.kind, Math.max(0, queue.offset - queue.limit)) }}>Previous queue page</Button><Button variant="secondary" disabled={busy || !queue.has_more} onClick={() => { void loadQueue(queue.kind, queue.offset + queue.limit) }}>More queue items</Button></div></section>}
      <UploadForm busy={busy} upload={(file, metadata) => { void upload(file, metadata) }} />
      {filing && <FilingPanel key={filing.id} job={filing} metrics={metrics} busy={busy} refresh={() => { if (api) void execute(async (signal) => { const job = await api.filing(filing.id, signal); const catalog = await api.read('metrics', '/v1/admin/workspace/metrics', signal); if (!signal.aborted) { setFiling(job); setMetrics(catalog.items) } }) }} start={(ids) => { void startProcessing(ids) }} />}
      {processing && <ProcessingPanel job={processing} busy={busy} refresh={() => { if (api) void execute(async (signal) => { const job = await api.processing(processing.id, signal); if (!signal.aborted) setProcessing(job) }) }} dispatch={() => { if (api) void execute(async (signal) => { const receipt = await api.read('dispatch', `/v1/admin/processing/jobs/${processing.id}/dispatch`, signal, {}); if (!signal.aborted) setMessage(receipt.dispatched ? 'Pending workflow dispatched.' : 'No dispatch was necessary; refresh the stored workflow.') }) }} review={(id) => { void reviewRun(id) }} validate={(id) => { void validateCandidates(id) }} />}
      {reviews && <ReviewPanel page={reviews} busy={busy} load={(filter, offset) => { void reviewRun(reviews.run_id, filter, offset) }} inspect={(item, span) => { void inspect(span, reviews.parse_version_id, item.result.context_supports, item.draft.supports) }} decide={(item, decision, note) => { void saveReview(item, decision, note) }} select={addSelection} revalidate={() => { void validateCandidates(reviews.candidate_run_id) }} />}
      <PublicationForm key={draftNumber} head={head} selections={selections} busy={busy} invalidate={() => { setManifest(null); setPublished(false); setSource(null) }} remove={(id) => { setSelections(selections.filter((item) => item.candidate_id !== id)); setManifest(null); setSource(null) }} create={(payload) => { void createDraft(payload) }} />
      <Button className="mt-3" variant="secondary" disabled={busy} onClick={() => { setSelections([]); setManifest(null); setSource(null); setPublished(false); setDraftNumber(draftNumber + 1); pending.current.clear() }}>Start a new publication draft</Button>
      {manifest && <BuildPanel key={manifest.id} manifest={manifest} published={published} busy={busy} publish={() => { void publishBuild('publish') }} rebuild={() => { void publishBuild('rebuild') }} inspect={(span, parse, contexts, supports) => { void inspect(span, parse, contexts, supports) }} />}
      {source && <SourceViewer key={`${source.evidence.record.id}:${source.evidence.source_sha256}`} source={source} bytes={source.bytes} />}
    </>}
    {busy && <p role="status" className="mt-4 text-sm text-muted">Checking stored state…</p>}{message && <p role="alert" className="mt-4 rounded border border-line bg-white p-4 text-sm">{message}</p>}
  </section>
}
