import { useEffect, useRef, useState } from 'react'
import { Button } from '../components/Button'
import { SourceViewer } from '../published/SourceViewer'
import type { CompanyPage, FactPage } from '../published/api'
import { definitionInput, ModuleApi, ModuleError, orderInput } from './api'
import { confirmOrder, pendingOrder, retainOrder } from './pending'
import { DraftQueue } from './DraftQueue'
import { Analytics } from './Analytics'
import { StarterDrafts } from './StarterDrafts'
import type { ExampleInput, GlossaryVersion, LearningExplanation, LedgerPage, OrderReceipt, OrderRequest, PortfolioAccount, PublishedEvidence, ReviewedDefinition, StoredDefinition } from './generated'

const inputClass = 'mt-1 min-h-11 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink'
const exampleOperations = ['ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE', 'PERCENT_CHANGE'] as const
function message(error: unknown): string { return error instanceof Error ? error.message : 'The operation could not be completed.' }

function useCompanies(api: ModuleApi) {
  const [companies, setCompanies] = useState<CompanyPage | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    void api.published.current(controller.signal).then(async (view) => {
      const result = await api.published.companies({ corpus: view.corpus_version_id, historical: false, asOf: '' }, '', 0, controller.signal)
      if (!controller.signal.aborted) setCompanies(result)
    }).catch(() => { if (!controller.signal.aborted) setError('Published company context is unavailable. The glossary and virtual account can still be used.') })
    return () => controller.abort()
  }, [api])
  return { companies, error }
}

export function ModuleWorkspace({ mode }: { mode: 'learning' | 'portfolio' }) {
  const [api, setApi] = useState<ModuleApi | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const title = mode === 'learning' ? 'Financial learning' : 'Virtual portfolio'
  return <section id={mode === 'learning' ? 'financial-learning' : 'virtual-portfolio'} className="border-t border-line py-10" aria-labelledby="module-workspace-heading">
    <h2 id="module-workspace-heading" className="text-2xl font-semibold">{title}</h2>
    <p className="mt-3 max-w-3xl text-sm leading-6 text-muted">{mode === 'learning' ? 'Read reviewed definitions, inspect their sources and connect them to published filing context.' : 'Practice with a virtual account and an immutable order history. Quote availability is shown explicitly; no real money is used.'}</p>
    {!api ? <form className="mt-6 grid max-w-2xl gap-4 sm:grid-cols-2" onSubmit={(event) => {
      event.preventDefault(); controller.current?.abort(); const active = new AbortController(); controller.current = active; setBusy(true); setError('')
      void ModuleApi.login(username, password, active.signal).then((session) => { if (!active.signal.aborted) { setApi(session); setPassword('') } }).catch((failure: unknown) => { if (!active.signal.aborted) setError(message(failure)) }).finally(() => { if (!active.signal.aborted) setBusy(false) })
    }}>
      <label className="text-sm font-semibold">Username<input autoComplete="username" className={inputClass} value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
      <label className="text-sm font-semibold">Password<input type="password" autoComplete="current-password" className={inputClass} value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
      <Button type="submit" disabled={busy} className="sm:col-span-2">{busy ? 'Signing in…' : `Sign in to ${mode === 'learning' ? 'financial learning' : 'virtual portfolio'}`}</Button>
    </form> : <>
      <div className="mt-5 flex items-center justify-between gap-3 text-sm"><p>Signed in as {api.user.username}</p><Button variant="secondary" onClick={() => { controller.current?.abort(); setApi(null); setPassword(''); setError('') }}>Sign out of learning and portfolio</Button></div>
      {mode === 'learning' ? <LearningPanel key={`learning-${api.user.id}`} api={api} /> : <PortfolioPanel key={`portfolio-${api.user.id}`} api={api} />}
    </>}
    {error && <p role="alert" className="mt-4 rounded-lg border border-line bg-white p-4 text-sm">{error}</p>}
  </section>
}

function Definition({ item }: { item: StoredDefinition }) {
  return <div className="space-y-3">
    <h3 className="text-lg font-semibold">{item.draft.term}</h3>
    <p className="whitespace-pre-wrap text-sm leading-6">{item.draft.definition}</p>
    <ul className="space-y-2 text-sm">{item.draft.sources.map((source, index) => <li key={index}><a href={source.url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">{source.title}</a>{source.location ? ` · ${source.location}` : ''}</li>)}</ul>
    {item.calculation && <div className="rounded-lg bg-paper p-3 text-sm"><p className="font-semibold">Educational example</p><p className="mt-2">{item.calculation.input.explanation}</p><p className="mt-2 break-words">{item.calculation.formula} · inputs {item.calculation.input.left}, {item.calculation.input.right} · result {item.calculation.result} {item.calculation.result_unit}</p>{item.calculation.rounding !== 'EXACT' && <p className="mt-1 text-muted">Rounded to 12 decimal places using half-even rounding.</p>}</div>}
  </div>
}

function LearningPanel({ api }: { api: ModuleApi }) {
  const [glossary, setGlossary] = useState<GlossaryVersion | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [term, setTerm] = useState('')
  const [definition, setDefinition] = useState('')
  const [sourceTitle, setSourceTitle] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [sourceLocation, setSourceLocation] = useState('')
  const [hasExample, setHasExample] = useState(false)
  const [exampleOperation, setExampleOperation] = useState<ExampleInput['operation']>('ADD')
  const [exampleLeft, setExampleLeft] = useState('')
  const [exampleRight, setExampleRight] = useState('')
  const [exampleUnit, setExampleUnit] = useState('')
  const [exampleExplanation, setExampleExplanation] = useState('')
  const [draft, setDraft] = useState<StoredDefinition | null>(null)
  const [savedId, setSavedId] = useState('')
  const [reviewed, setReviewed] = useState<ReviewedDefinition | null>(null)
  const [note, setNote] = useState('')
  const [selectedTerm, setSelectedTerm] = useState('')
  const [company, setCompany] = useState('')
  const [facts, setFacts] = useState<FactPage | null>(null)
  const [metric, setMetric] = useState('')
  const [observation, setObservation] = useState('')
  const [context, setContext] = useState<LearningExplanation | null>(null)
  const [source, setSource] = useState<{ record: PublishedEvidence; bytes: Uint8Array<ArrayBuffer> } | null>(null)
  const active = useRef<AbortController | null>(null)
  const { companies, error: companyError } = useCompanies(api)
  useEffect(() => {
    const controller = new AbortController()
    void api.read('learning_status', '/v1/learning/status', controller.signal).then(async (status) => {
      const value = status.glossary_version_id ? await api.read('glossary', `/v1/learning/glossary/${status.glossary_version_id}`, controller.signal) : null
      if (!controller.signal.aborted) { setGlossary(value); setLoaded(true) }
    }).catch((failure: unknown) => { if (!controller.signal.aborted) setError(message(failure)) })
    return () => { controller.abort(); active.current?.abort() }
  }, [api])
  useEffect(() => {
    if (!companies || !company) return
    const controller = new AbortController()
    void api.published.facts({ corpus: companies.view.corpus_version_id, historical: false, asOf: '' }, company, 0, controller.signal).then((value) => { if (!controller.signal.aborted) setFacts(value) }).catch((failure: unknown) => { if (!controller.signal.aborted) setError(message(failure)) })
    return () => controller.abort()
  }, [api, companies, company])

  function run(action: (signal: AbortSignal) => Promise<void>): void {
    active.current?.abort(); const controller = new AbortController(); active.current = controller; setBusy(true); setError('')
    void action(controller.signal).catch((failure: unknown) => { if (!controller.signal.aborted) setError(message(failure)) }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
  }
  async function loadDraft(identity: string, signal: AbortSignal): Promise<void> {
    const value = await api.read('definition', `/v1/learning/drafts/${encodeURIComponent(identity)}`, signal)
    let recorded: ReviewedDefinition | null = null
    try { recorded = await api.read('reviewed', `/v1/learning/drafts/${value.id}/review`, signal) } catch (failure: unknown) { if (!(failure instanceof ModuleError && failure.status === 404)) throw failure }
    setSavedId(value.id); setDraft(value); setReviewed(recorded); setNote(recorded?.review.note ?? '')
  }
  const selected = glossary?.definitions.find((item) => item.definition.id === selectedTerm)
  const choices = facts?.facts.filter((item) => item.observation.metric_id !== null && selected?.definition.draft.metric_ids?.includes(item.observation.metric_id)) ?? []
  return <div className="mt-6 space-y-7">
    <Button variant="secondary" disabled={busy} onClick={() => run(async (signal) => {
      const status = await api.read('learning_status', '/v1/learning/status', signal)
      const version = status.glossary_version_id ? await api.read('glossary', `/v1/learning/glossary/${status.glossary_version_id}`, signal) : null
      setGlossary(version); setLoaded(true); setContext(null); setSource(null)
    })}>Refresh reviewed glossary</Button>
    {!loaded && !error && <p role="status">Loading reviewed glossary…</p>}
    {loaded && !glossary && <p role="status" className="rounded-lg bg-paper p-4 text-sm">No glossary has been published. An administrator must draft, review and publish definitions first.</p>}
    {glossary && <div className="grid gap-4 md:grid-cols-2">{glossary.definitions.map((item) => <article key={item.definition.id} className="rounded-xl border border-line bg-white p-5"><Definition item={item.definition} /><p className="mt-4 text-xs text-muted">Approved definition · glossary version {glossary.glossary_version_id}</p></article>)}</div>}
    <section className="rounded-xl border border-line bg-white p-5" aria-labelledby="learning-context-heading">
      <h3 id="learning-context-heading" className="text-lg font-semibold">Published filing context</h3>
      {companyError && <p className="mt-3 text-sm">{companyError}</p>}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="text-sm">Definition<select className={inputClass} value={selectedTerm} onChange={(event) => { setSelectedTerm(event.target.value); setContext(null); setSource(null); setObservation('') }}><option value="">Select a reviewed definition</option>{glossary?.definitions.map((item) => <option key={item.definition.id} value={item.definition.id}>{item.definition.draft.term}</option>)}</select></label>
        <label className="text-sm">Company<select className={inputClass} value={company} onChange={(event) => { setCompany(event.target.value); setFacts(null); setContext(null); setSource(null); setObservation(''); setMetric('') }}><option value="">Select a published company</option>{companies?.companies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="text-sm sm:col-span-2">Disclosure<select className={inputClass} value={observation} onChange={(event) => { setObservation(event.target.value); setContext(null); setSource(null) }}><option value="">Select a matching published disclosure</option>{choices.map((item) => <option key={item.observation.id} value={item.observation.id}>{item.metric.label}: {item.observation.raw_text.slice(0, 160)}</option>)}</select></label>
      </div>
      {selected && !(selected.definition.draft.metric_ids?.length) && <p className="mt-3 text-sm">This definition has no reviewed filing-metric link. Its general definition and sources remain available.</p>}
      <Button className="mt-4" disabled={busy || !glossary || !companies || !observation || !selectedTerm} onClick={() => run(async (signal) => {
        if (!glossary || !companies) return
        const result = await api.read('context', '/v1/learning/context', signal, { glossary_version_id: glossary.glossary_version_id, definition_id: selectedTerm, corpus_version_id: companies.view.corpus_version_id, observation_id: observation, as_of_date: null })
        if (result.definition.definition.id !== selectedTerm || result.observation.id !== observation || result.glossary_version_id !== glossary.glossary_version_id || result.view.corpus_version_id !== companies.view.corpus_version_id) throw new ModuleError(0, 'The explanation differs from the selected context.')
        setContext(result); setSource(null)
      })}>Show reviewed context</Button>
      {context && <div className="mt-5 space-y-3"><p className="whitespace-pre-wrap text-sm leading-6">{context.observation.raw_text}</p><p className="text-xs text-muted">Original published disclosure · no generated paraphrase</p>{context.evidence.map((record) => <Button key={record.evidence.record.id} variant="secondary" disabled={busy} onClick={() => run(async (signal) => {
        const bytes = await api.published.pdf({ corpus: context.view.corpus_version_id, historical: false, asOf: context.view.as_of_date ?? '' }, context.observation.id, record.evidence.source_sha256, signal)
        setSource({ record, bytes })
      })}>View source page {record.evidence.record.source.page_index + 1}</Button>)}</div>}
      {source && <SourceViewer source={source.record} bytes={source.bytes} />}
    </section>
    {api.user.role === 'admin' && <section className="rounded-xl border border-line bg-paper p-5" aria-labelledby="definition-authoring-heading">
      <h3 id="definition-authoring-heading" className="text-lg font-semibold">Review and publish definitions</h3>
      <p className="mt-2 text-sm text-muted">Drafts stay private until an explicit review and publication. Review the definition, its sources and any metric link before approval.</p>
      <div className="mt-5"><StarterDrafts api={api} busy={busy} onUse={(value) => {
        const source = value.sources[0]; if (!source) return
        setTerm(value.term); setDefinition(value.definition); setSourceTitle(source.title); setSourceUrl(source.url); setSourceLocation(source.location ?? '')
        const example = value.example
        setHasExample(Boolean(example)); setExampleOperation(example?.operation ?? 'ADD'); setExampleLeft(example?.left ?? ''); setExampleRight(example?.right ?? ''); setExampleUnit(example?.unit ?? ''); setExampleExplanation(example?.explanation ?? '')
        setDraft(null); setReviewed(null); setSavedId(''); setNote(''); setMetric(''); setError('')
      }} /></div>
      <div className="mt-5"><DraftQueue api={api} onOpen={(identity) => run((signal) => loadDraft(identity, signal))} /></div>
      <form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={(event) => {
        event.preventDefault()
        run(async (signal) => {
          const selectedMetric = facts?.facts.find((item) => item.metric.id === metric)?.metric.id
          const input = definitionInput({ term, definition, sources: [{ title: sourceTitle, url: sourceUrl, location: sourceLocation.trim() || null }], metric_ids: selectedMetric ? [selectedMetric] : [], example: hasExample ? { kind: 'AUTHORED_EDUCATIONAL_EXAMPLE', operation: exampleOperation, left: exampleLeft, right: exampleRight, unit: exampleUnit, explanation: exampleExplanation } : null })
          const value = await api.read('definition', '/v1/learning/drafts', signal, input)
          setDraft(value); setSavedId(value.id); setReviewed(null); setNote('')
        })
      }}>
        <label className="text-sm">Term<input className={inputClass} value={term} onChange={(event) => setTerm(event.target.value)} maxLength={120} required /></label>
        <label className="text-sm">Source title<input className={inputClass} value={sourceTitle} onChange={(event) => setSourceTitle(event.target.value)} maxLength={200} required /></label>
        <label className="text-sm sm:col-span-2">Definition<textarea className={inputClass} value={definition} onChange={(event) => setDefinition(event.target.value)} rows={4} maxLength={4000} required /></label>
        <label className="text-sm sm:col-span-2">Source URL<input type="url" className={inputClass} value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} maxLength={2048} required /></label>
        <label className="text-sm sm:col-span-2">Source location (optional)<input className={inputClass} value={sourceLocation} onChange={(event) => setSourceLocation(event.target.value)} maxLength={200} /></label>
        <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={hasExample} onChange={(event) => setHasExample(event.target.checked)} />Include an authored educational example</label>
        {hasExample && <fieldset className="grid gap-4 rounded-lg border border-line p-4 sm:col-span-2 sm:grid-cols-2"><legend className="px-2 text-sm font-semibold">Educational example inputs</legend>
          <label className="text-sm">Operation<select className={inputClass} value={exampleOperation} onChange={(event) => setExampleOperation(exampleOperations.find((operation) => operation === event.target.value) ?? 'ADD')}>{exampleOperations.map((operation) => <option key={operation} value={operation}>{operation.replaceAll('_', ' ')}</option>)}</select></label>
          <label className="text-sm">Input unit<input className={inputClass} value={exampleUnit} onChange={(event) => setExampleUnit(event.target.value)} maxLength={80} required /></label>
          <label className="text-sm">Left decimal input<input className={inputClass} inputMode="decimal" value={exampleLeft} onChange={(event) => setExampleLeft(event.target.value)} required /></label>
          <label className="text-sm">Right decimal input<input className={inputClass} inputMode="decimal" value={exampleRight} onChange={(event) => setExampleRight(event.target.value)} required /></label>
          <label className="text-sm sm:col-span-2">Example explanation<textarea className={inputClass} value={exampleExplanation} onChange={(event) => setExampleExplanation(event.target.value)} maxLength={1000} rows={2} required /></label>
          <p className="text-xs text-muted sm:col-span-2">The backend calculates the result before review. Percentage change uses left as the positive baseline and right as the later value. Examples are educational inputs, separate from filing facts.</p>
        </fieldset>}
        <label className="text-sm sm:col-span-2">Matching published metric (optional)<select className={inputClass} value={metric} onChange={(event) => setMetric(event.target.value)}><option value="">General learning definition</option>{[...new Map(facts?.facts.map((item) => [item.metric.id, item.metric]) ?? []).values()].map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select><span className="mt-1 block text-xs text-muted">Select a company above to load its available metrics.</span></label>
        <Button type="submit" disabled={busy} className="sm:col-span-2">Save definition draft</Button>
      </form>
      <div className="mt-6 flex flex-wrap items-end gap-3"><label className="min-w-0 grow text-sm">Saved draft ID<input className={inputClass} value={savedId} onChange={(event) => setSavedId(event.target.value)} /></label><Button variant="secondary" disabled={busy || !savedId} onClick={() => run(async (signal) => {
        await loadDraft(savedId, signal)
      })}>Load saved draft</Button></div>
      {draft && <div className="mt-5 rounded-lg border border-line bg-white p-4"><Definition item={draft} /><label className="mt-5 block text-sm">Review note<textarea className={inputClass} value={note} onChange={(event) => setNote(event.target.value)} rows={2} maxLength={1000} /></label><div className="mt-3 flex flex-wrap gap-3">{(['APPROVE', 'REJECT'] as const).map((decision) => <Button key={decision} variant={decision === 'APPROVE' ? 'primary' : 'secondary'} disabled={busy || !note.trim() || reviewed !== null} onClick={() => run(async (signal) => { setReviewed(await api.read('reviewed', `/v1/learning/drafts/${draft.id}/review`, signal, { decision, note })) })}>{decision === 'APPROVE' ? 'Approve definition' : 'Reject definition'}</Button>)}</div>{reviewed && <p role="status" className="mt-3 text-sm">Review recorded: {reviewed.review.decision}</p>}<Button className="mt-4" disabled={busy || reviewed?.review.decision !== 'APPROVE'} onClick={() => run(async (signal) => {
        const retained = glossary?.definitions.filter((item) => item.definition.draft.term.toLowerCase() !== draft.draft.term.toLowerCase()).map((item) => item.definition.id) ?? []
        const version = await api.read('glossary', '/v1/learning/versions', signal, { definition_ids: [...retained, draft.id], parent_glossary_version_id: glossary?.glossary_version_id ?? null })
        setGlossary(version); setLoaded(true); setDraft(null); setReviewed(null); setContext(null); setSource(null)
      })}>Publish approved definition</Button></div>}
    </section>}
    {error && <p role="alert" className="rounded-lg border border-line bg-white p-4 text-sm">{error}</p>}
  </div>
}

function PortfolioPanel({ api }: { api: ModuleApi }) {
  const [account, setAccount] = useState<PortfolioAccount | null>(null)
  const [ledger, setLedger] = useState<LedgerPage | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [company, setCompany] = useState('')
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [quantity, setQuantity] = useState('1')
  const [pending, setPending] = useState<OrderRequest | null>(() => pendingOrder(api.user.id))
  const [notCommitted, setNotCommitted] = useState(false)
  const [receipt, setReceipt] = useState<OrderReceipt | null>(null)
  const { companies, error: companyError } = useCompanies(api)
  const active = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void api.portfolioSnapshot(controller.signal).then(({ account: current, ledger: history }) => {
      if (!controller.signal.aborted) { setAccount(current); setLedger(history); setLoaded(true) }
    }).catch((failure: unknown) => { if (!controller.signal.aborted) { if (!(failure instanceof ModuleError && failure.status === 404)) setError(message(failure)); setLoaded(true) } })
    return () => { controller.abort(); active.current?.abort() }
  }, [api])
  function run(action: (signal: AbortSignal) => Promise<void>): void {
    active.current?.abort(); const controller = new AbortController(); active.current = controller; setBusy(true); setError('')
    void action(controller.signal).catch((failure: unknown) => { if (!controller.signal.aborted) setError(message(failure)) }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
  }
  async function refresh(signal: AbortSignal): Promise<void> {
    const { account: current, ledger: history } = await api.portfolioSnapshot(signal)
    setAccount(current); setLedger(history)
  }
  function submit(request: OrderRequest): void {
    try { retainOrder(api.user.id, request) } catch (failure: unknown) { setError(message(failure)); return }
    setPending(request)
    setNotCommitted(false)
    run(async (signal) => {
      let result: OrderReceipt
      try { result = await api.order(request, signal) } catch (failure: unknown) {
        if (failure instanceof ModuleError && [403, 404, 422].includes(failure.status)) setNotCommitted(true)
        throw failure
      }
      confirmOrder(api.user.id); setReceipt(result); setPending(null)
      try { await refresh(signal) } catch { setError('The order outcome is recorded. Its balance refresh is unavailable; refresh the portfolio to synchronize.') }
    })
  }
  const name = (identity: string) => companies?.companies.find((item) => item.id === identity)?.name ?? identity
  return <div className="mt-6 space-y-5">
    <p className="rounded-lg bg-paper p-4 text-sm">Quotes are unavailable until a reviewed price source is configured. Submitted virtual orders receive a recorded rejection without changing cash or holdings. Current market valuation is unavailable.</p>
    {!loaded && <p role="status">Loading virtual account…</p>}
    {loaded && !account && <Button disabled={busy} onClick={() => run(async (signal) => { setAccount(await api.read('portfolio', '/v1/portfolio/accounts', signal, {})); await refresh(signal) })}>Create virtual account with INR 100000.00</Button>}
    {account && <>
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line bg-white p-5"><div><h3 className="text-lg font-semibold">Virtual cash: INR {account.state.cash}</h3><p className="mt-2 text-sm text-muted">{account.committed_orders} recorded orders · whole shares · zero fees</p></div><Button variant="secondary" disabled={busy || pending !== null} onClick={() => run(refresh)}>Refresh portfolio</Button></div>
      <form className="grid gap-4 rounded-xl border border-line bg-white p-5 sm:grid-cols-3" onSubmit={(event) => { event.preventDefault(); if (!companies || pending) return; try { submit(orderInput({ request_id: crypto.randomUUID(), corpus_version_id: companies.view.corpus_version_id, company_id: company, side, quantity: Number(quantity) })) } catch (failure: unknown) { setError(message(failure)) } }}>
        <label className="text-sm">Published company<select className={inputClass} value={company} onChange={(event) => setCompany(event.target.value)} disabled={pending !== null} required><option value="">Select a company</option>{companies?.companies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="text-sm">Virtual action<select className={inputClass} value={side} onChange={(event) => setSide(event.target.value === 'SELL' ? 'SELL' : 'BUY')} disabled={pending !== null}><option value="BUY">Buy</option><option value="SELL">Sell</option></select></label>
        <label className="text-sm">Whole shares<input type="number" min="1" max="1000000" step="1" className={inputClass} value={quantity} onChange={(event) => setQuantity(event.target.value)} disabled={pending !== null} required /></label>
        <Button type="submit" disabled={busy || pending !== null || !company || !companies} className="sm:col-span-3">Submit virtual order</Button>
        {companyError && <p className="text-sm sm:col-span-3">{companyError}</p>}
      </form>
      {pending && <div className="rounded-lg border border-line bg-white p-4"><p className="text-sm">This order has no confirmed response. Retry with the same request key to avoid duplicate execution. The request is retained for this browser tab when you sign in again.</p><p className="mt-2 break-all text-xs text-muted">Request key: {pending.request_id}</p><Button className="mt-3" disabled={busy} onClick={() => submit(pending)}>Retry same virtual order</Button>{notCommitted && <Button className="ml-3 mt-3" variant="secondary" disabled={busy} onClick={() => { confirmOrder(api.user.id); setPending(null); setNotCommitted(false) }}>Clear declined request</Button>}</div>}
      {receipt && <p role="status" className="rounded-lg bg-paper p-4 text-sm">Recorded order #{receipt.entry.sequence}: {receipt.entry.evaluation.state} · {receipt.entry.evaluation.reason.replaceAll('_', ' ')}</p>}
      <section className="rounded-xl border border-line bg-white p-5"><h3 className="font-semibold">Holdings</h3>{account.state.holdings.length ? <ul className="mt-3 space-y-2 text-sm">{account.state.holdings.map((item) => <li key={item.company_id}>{name(item.company_id)} · {item.quantity} shares</li>)}</ul> : <p className="mt-3 text-sm text-muted">No virtual holdings.</p>}</section>
      <Analytics key={account.portfolio_version_id} api={api} account={account.account_id} version={account.portfolio_version_id} companyName={name} />
      <section className="rounded-xl border border-line bg-white p-5"><h3 className="font-semibold">Immutable virtual history</h3>{ledger?.entries.length ? <ol className="mt-3 space-y-3 text-sm">{ledger.entries.map((entry) => <li key={entry.id} className="border-b border-line pb-3">#{entry.sequence} · {entry.request.side} {entry.request.quantity} {name(entry.request.company_id)} · {entry.evaluation.state} · {entry.evaluation.reason.replaceAll('_', ' ')}<span className="mt-1 block text-xs text-muted">Cash after outcome: INR {entry.evaluation.after.cash}</span></li>)}</ol> : <p className="mt-3 text-sm text-muted">No virtual orders recorded.</p>}{ledger && ledger.offset + ledger.entries.length < ledger.total && <Button variant="secondary" className="mt-3" disabled={busy} onClick={() => run(async (signal) => { setLedger(await api.ledgerSnapshot(account, signal, ledger.offset + ledger.entries.length)) })}>Next history page</Button>}</section>
    </>}
    {error && <p role="alert" className="rounded-lg border border-line bg-white p-4 text-sm">{error}</p>}
  </div>
}
