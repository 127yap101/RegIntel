import { useEffect, useRef, useState } from 'react'
import { Button } from '../components/Button'
import { PublishedApi, ReadError } from './api'
import type { CompanyGraph, CompanyPage, FactPage, PublishedEvidence, ReadOptions } from './api'
import type { PublishedObservation } from './generated'
import { RelationGraph } from './RelationGraph'
import { SourceViewer } from './SourceViewer'
import { FinancialContext } from './FinancialContext'
import { AnswerPanel } from '../retrieval/AnswerPanel'
import type { AnswerInput, AnswerResult } from '../retrieval/wire'
import { ComparisonPanel } from '../analysis/ComparisonPanel'
import type { ComparisonInput, ComparisonResult, QuotesResult } from '../analysis/wire'

const inputClass = 'mt-1 min-h-11 w-full rounded-lg border border-line bg-white px-3 text-sm text-ink'

export function Explorer() {
  const [api, setApi] = useState<PublishedApi | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [corpus, setCorpus] = useState('')
  const [historical, setHistorical] = useState(false)
  const [asOf, setAsOf] = useState('')
  const [query, setQuery] = useState('')
  const [options, setOptions] = useState<ReadOptions | null>(null)
  const [companies, setCompanies] = useState<CompanyPage | null>(null)
  const [facts, setFacts] = useState<FactPage | null>(null)
  const [graph, setGraph] = useState<CompanyGraph | null>(null)
  const [answer, setAnswer] = useState<AnswerResult | null>(null)
  const [comparison, setComparison] = useState<ComparisonResult | null>(null)
  const [quotes, setQuotes] = useState<QuotesResult | null>(null)
  const [source, setSource] = useState<{ evidence: PublishedEvidence; bytes: Uint8Array<ArrayBuffer> } | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const operation = useRef<AbortController | null>(null)
  useEffect(() => () => operation.current?.abort(), [])

  function clearPrivate(): void {
    setApi(null); setCompanies(null); setFacts(null); setGraph(null); setSource(null); setAnswer(null)
    setOptions(null); setCorpus(''); setPassword(''); setQuery(''); setAsOf(''); setHistorical(false); setComparison(null); setQuotes(null)
  }

  function logout(): void { operation.current?.abort(); clearPrivate(); setBusy(false); setMessage('Signed out.') }

  async function execute(action: (signal: AbortSignal) => Promise<void>): Promise<void> {
    operation.current?.abort()
    const controller = new AbortController()
    operation.current = controller
    setBusy(true); setMessage('')
    try { await action(controller.signal) }
    catch (error: unknown) {
      if (controller.signal.aborted) return
      if (error instanceof ReadError && error.auth) clearPrivate()
      setMessage(error instanceof ReadError ? error.message : 'Published data could not be verified. Please retry.')
    } finally { if (!controller.signal.aborted) setBusy(false) }
  }

  function clearSelection(): void { setFacts(null); setGraph(null); setSource(null); setAnswer(null); setComparison(null) }

  async function compare(input: ComparisonInput): Promise<void> {
    if (!api || !options) return
    setComparison(null); setSource(null); setQuotes(null)
    await execute(async (signal) => {
      const result = await api.compare(options, input, signal)
      if (!signal.aborted) setComparison(result)
      const availability = await api.quotes(signal)
      if (!signal.aborted) setQuotes(availability)
    })
  }

  async function ask(input: AnswerInput): Promise<void> {
    if (!api || !options) return
    setAnswer(null); setSource(null)
    await execute(async (signal) => {
      const result = await api.answer(options, { ...input, ...(facts ? { company: facts.company.id } : {}) }, signal)
      if (!signal.aborted) setAnswer(result)
    })
  }

  async function signIn(): Promise<void> {
    const submittedPassword = password
    setPassword('')
    await execute(async (signal) => {
      const client = await PublishedApi.login(username, submittedPassword, signal)
      const current = await client.current(signal)
      const selected = { corpus: current.corpus_version_id, historical: false, asOf: '' }
      const results = await client.companies(selected, '', 0, signal)
      if (signal.aborted) return
      setApi(client); setOptions(selected); setCorpus(selected.corpus); setCompanies(results)
    })
  }

  async function search(offset = 0): Promise<void> {
    if (!api) return
    clearSelection(); setCompanies(null)
    const selected = { corpus, historical, asOf }
    await execute(async (signal) => {
      const results = await api.companies(selected, query, offset, signal)
      if (!signal.aborted) { setOptions(selected); setCompanies(results) }
    })
  }

  async function chooseCompany(company: string, offset = 0): Promise<void> {
    if (!api || !options) return
    clearSelection()
    await execute(async (signal) => {
      const results = await Promise.allSettled([api.facts(options, company, offset, signal), api.graph(options, company, signal)])
      if (signal.aborted) return
      for (const result of results) if (result.status === 'rejected' && result.reason instanceof ReadError && result.reason.auth) throw result.reason
      const factResult = results[0]; const graphResult = results[1]
      if (factResult.status === 'fulfilled') setFacts(factResult.value)
      if (graphResult.status === 'fulfilled') setGraph(graphResult.value)
      if (factResult.status === 'rejected' || graphResult.status === 'rejected') setMessage('Part of this view is unavailable. Available published results are shown; retry to load the rest.')
    })
  }

  async function inspect(observation: string, evidenceId: string): Promise<void> {
    if (!api || !options) return
    setSource(null)
    await execute(async (signal) => {
      const evidence = await api.evidence(options, observation, evidenceId, signal)
      const bytes = await api.pdf(options, observation, evidence.evidence.source_sha256, signal)
      if (!signal.aborted) setSource({ evidence, bytes })
    })
  }

  function supportButtons(observation: PublishedObservation) {
    const spans = [...observation.supports, ...observation.context_supports.map((item) => item.span)]
    const ids = [...new Set(spans.map((span) => span.evidence_id))]
    return <div className="mt-4 flex flex-wrap gap-2">{ids.map((identity, index) => <Button key={identity} variant="secondary" disabled={busy} onClick={() => { void inspect(observation.id, identity) }}>Inspect source {index + 1}</Button>)}</div>
  }

  return <section id="filing-explorer" aria-labelledby="filings-heading" className="scroll-mt-6 border-t border-line py-10">
    <h2 id="filings-heading" className="text-2xl font-semibold tracking-tight">Published filing explorer</h2>
    <p className="mt-3 max-w-3xl text-sm leading-6 text-muted">Read reviewed disclosures and inspect their original filing pages. A filing statement retains its conditions and source context.</p>
    {!api ? <form className="mt-6 grid max-w-xl gap-4 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); void signIn() }}>
      <label className="text-sm font-medium">Username<input className={inputClass} autoComplete="username" name="username" value={username} maxLength={64} required onChange={(event) => setUsername(event.target.value)} /></label>
      <label className="text-sm font-medium">Password<input className={inputClass} autoComplete="current-password" name="password" type="password" value={password} maxLength={1024} required onChange={(event) => setPassword(event.target.value)} /></label>
      <Button type="submit" disabled={busy} className="sm:col-span-2">{busy ? 'Signing in…' : 'Sign in to inspect filings'}</Button>
    </form> : <>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3"><p className="max-w-full break-all text-xs text-muted">Viewing corpus: {options?.corpus}</p><Button variant="secondary" onClick={logout}>Sign out</Button></div>
      <form className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(event) => { event.preventDefault(); void search() }}>
        <label className="text-sm font-medium">Company name or identifier<input className={inputClass} value={query} maxLength={120} onChange={(event) => setQuery(event.target.value)} /></label>
        <label className="text-sm font-medium">Published corpus version<input className={inputClass} value={corpus} required onChange={(event) => setCorpus(event.target.value)} /></label>
        <label className="text-sm font-medium">As-of date (optional)<input className={inputClass} type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label>
        <div className="flex flex-col justify-end gap-3"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={historical} onChange={(event) => setHistorical(event.target.checked)} />Include accepted history</label><Button type="submit" disabled={busy}>Apply view</Button></div>
      </form>
      {companies && <div className="mt-6">
        {companies.view.state === 'TEMPORAL_SUPPORT_UNAVAILABLE' ? <p className="rounded-lg border border-amber p-4 text-sm">This date view is unavailable because source or effect dates lack support. No financial result is inferred.</p> : <>
          <p className="text-sm text-muted">{companies.total} published {companies.total === 1 ? 'company' : 'companies'} in this view.</p>
          <ul className="mt-3 flex flex-wrap gap-3">{companies.companies.map((company) => <li key={company.id}><Button disabled={busy} variant={facts?.company.id === company.id ? 'primary' : 'secondary'} onClick={() => { void chooseCompany(company.id) }}>{company.name}</Button></li>)}</ul>
          <div className="mt-3 flex gap-3">{companies.offset > 0 && <Button disabled={busy} variant="secondary" onClick={() => { void search(Math.max(0, companies.offset - companies.limit)) }}>Previous companies</Button>}{companies.offset + companies.limit < companies.total && <Button disabled={busy} variant="secondary" onClick={() => { void search(companies.offset + companies.limit) }}>More companies</Button>}</div>
        </>}
        {companies.view.unresolved_parent_filing_version_ids.length > 0 && <p className="mt-4 text-sm text-muted">Some amendment parents are unresolved. Disclosures have not been automatically replaced.</p>}
      </div>}
      {facts && <section aria-label="Published facts" className="mt-7">
        <h3 className="text-xl font-semibold">{facts.company.name}</h3>
        <p className="mt-2 text-sm text-muted">{facts.total} {options?.historical ? 'historical accepted' : 'active'} {facts.total === 1 ? 'disclosure' : 'disclosures'}{options?.asOf ? ` as of ${options.asOf}` : ''}.</p>
        <ul className="mt-4 space-y-4">{facts.facts.map(({ observation, metric }) => <li key={observation.id} className="rounded-xl border border-line bg-white p-5">
          <h4 className="font-semibold">{metric.label}</h4><blockquote className="mt-3 whitespace-pre-wrap text-sm leading-7">{observation.raw_text}</blockquote>
          <FinancialContext quantity={observation.quantity} />
          <p className="mt-3 break-all text-xs text-muted">Accepted observation {observation.id} · source date {observation.source_published_on ?? 'unknown'}</p>
          {supportButtons(observation)}
        </li>)}</ul>
        <div className="mt-4 flex gap-3">{facts.offset > 0 && <Button disabled={busy} variant="secondary" onClick={() => { void chooseCompany(facts.company.id, Math.max(0, facts.offset-facts.limit)) }}>Previous disclosures</Button>}{facts.offset+facts.limit < facts.total && <Button disabled={busy} variant="secondary" onClick={() => { void chooseCompany(facts.company.id, facts.offset+facts.limit) }}>More disclosures</Button>}</div>
      </section>}
      {graph && <RelationGraph graph={graph} support={supportButtons} select={(identity) => { const edge = graph.edges.find((item) => item.id === identity); const evidence = edge?.supports[0]; if (edge && evidence) void inspect(edge.id, evidence.evidence_id) }} />}
      {options && companies && <ComparisonPanel key={`${options.corpus}:${options.historical}:${options.asOf}`} companies={companies} facts={facts} options={options} busy={busy} result={comparison} quotes={quotes} compare={(input) => { void compare(input) }} inspect={supportButtons} />}
      {options && <AnswerPanel answer={answer} busy={busy} ask={(input) => { void ask(input) }} inspect={(observation, evidence) => { void inspect(observation, evidence) }} />}
      {source && <SourceViewer key={`${source.evidence.observation_id}:${source.evidence.evidence.record.id}`} source={source.evidence} bytes={source.bytes} />}
    </>}
    {busy && api && <p className="mt-4 text-sm text-muted">Loading the selected published view…</p>}
    {message && <p role="alert" className="mt-4 rounded-lg border border-line bg-white p-4 text-sm">{message}</p>}
  </section>
}
