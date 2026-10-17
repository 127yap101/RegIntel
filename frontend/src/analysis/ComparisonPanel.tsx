import { useState } from 'react'
import { Button } from '../components/Button'
import { FinancialContext } from '../published/FinancialContext'
import type { CompanyPage, FactPage, ReadOptions } from '../published/api'
import type { PublishedObservation } from '../published/generated'
import type { ComparisonInput, ComparisonResult, QuotesResult } from './wire'

const inputClass = 'mt-1 min-h-11 w-full rounded-lg border border-line bg-white px-3 text-sm text-ink'
type Props = {
  companies: CompanyPage
  facts: FactPage | null
  options: ReadOptions
  busy: boolean
  result: ComparisonResult | null
  quotes: QuotesResult | null
  compare: (input: ComparisonInput) => void
  inspect: (observation: PublishedObservation) => React.ReactNode
}

export function ComparisonPanel({ companies, facts, options, busy, result, quotes, compare, inspect }: Props) {
  const [selected, setSelected] = useState<ReadonlyArray<{ id: string; name: string }>>([])
  const [metricSelection, setMetricSelection] = useState<ReadonlyArray<{ id: string; label: string }>>([])
  const metrics = metricSelection.map((metric) => metric.id)
  const [kind, setKind] = useState<'DURATION' | 'INSTANT'>('DURATION')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [instant, setInstant] = useState('')
  const [basis, setBasis] = useState<'STANDALONE' | 'CONSOLIDATED'>('CONSOLIDATED')
  const numeric = [...new Map((facts?.facts ?? []).filter((item) => item.metric.kind === 'numeric_fact').map((item) => [item.metric.id, item.metric])).values()]
  const metricChoices = [...new Map([...metricSelection, ...numeric].map((metric) => [metric.id, metric])).values()]
  const choices = [...new Map([...selected, ...companies.companies].map((company) => [company.id, company])).values()]

  function toggleCompany(company: { id: string; name: string }): void {
    setSelected((previous) => previous.some((item) => item.id === company.id) ? previous.filter((item) => item.id !== company.id) : previous.length < 4 ? [...previous, company] : previous)
  }

  return <section aria-labelledby="comparison-heading" className="mt-8 rounded-xl border border-line bg-paper p-5 sm:p-6">
    <h3 id="comparison-heading" className="text-xl font-semibold">Analysis &amp; comparison</h3>
    <p className="mt-3 text-sm leading-6 text-muted">Compare the same accepted metric at one period and reporting basis. The first company selected is the baseline. Inspect a company above to choose its published numeric metrics.</p>
    {options.historical ? <p className="mt-4 text-sm">Calculations require an active view. Turn off “Include accepted history” and apply the view to compare.</p> : <form className="mt-5 space-y-5" onSubmit={(event) => {
      event.preventDefault()
      compare({ companies: selected.map((item) => item.id), metrics, basis, period: { kind, start_date: kind === 'DURATION' ? start : null, end_date: kind === 'DURATION' ? end : null, instant_date: kind === 'INSTANT' ? instant : null, raw_label: null } })
    }}>
      <fieldset><legend className="text-sm font-semibold">Companies (select 2–4)</legend><div className="mt-3 flex flex-wrap gap-4">{choices.map((company) => <label key={company.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.some((item) => item.id === company.id)} disabled={busy || (selected.length === 4 && !selected.some((item) => item.id === company.id))} onChange={() => toggleCompany(company)} />{company.name}</label>)}</div><p className="mt-2 text-xs text-muted">Baseline: {selected[0]?.name ?? 'Select a company'}. More companies can be added from the search pages above.</p></fieldset>
      <fieldset><legend className="text-sm font-semibold">Numeric metrics from opened profiles (select 1–12)</legend>{metricChoices.length ? <div className="mt-3 flex flex-wrap gap-4">{metricChoices.map((metric) => <label key={metric.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={metrics.includes(metric.id)} disabled={busy || (metrics.length === 12 && !metrics.includes(metric.id))} onChange={() => setMetricSelection((previous) => previous.some((item) => item.id === metric.id) ? previous.filter((item) => item.id !== metric.id) : [...previous, metric])} />{metric.label}</label>)}</div> : <p className="mt-2 text-sm text-muted">No numeric metrics on this profile page. A comparison requires accepted numerical disclosures.</p>}{metrics.length > 0 && <p className="mt-2 text-xs text-muted">{metrics.length} selected metric(s). <button type="button" className="underline" disabled={busy} onClick={() => setMetricSelection([])}>Clear metrics</button></p>}</fieldset>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-sm font-medium">Period type<select className={inputClass} value={kind} onChange={(event) => setKind(event.target.value === 'INSTANT' ? 'INSTANT' : 'DURATION')}><option value="DURATION">Duration</option><option value="INSTANT">Instant</option></select></label>
        {kind === 'DURATION' ? <><label className="text-sm font-medium">Period start<input className={inputClass} type="date" required value={start} onChange={(event) => setStart(event.target.value)} /></label><label className="text-sm font-medium">Period end<input className={inputClass} type="date" required min={start} value={end} onChange={(event) => setEnd(event.target.value)} /></label></> : <label className="text-sm font-medium">Instant date<input className={inputClass} type="date" required value={instant} onChange={(event) => setInstant(event.target.value)} /></label>}
        <label className="text-sm font-medium">Comparison reporting basis<select className={inputClass} value={basis} onChange={(event) => setBasis(event.target.value === 'STANDALONE' ? 'STANDALONE' : 'CONSOLIDATED')}><option value="CONSOLIDATED">Consolidated</option><option value="STANDALONE">Standalone</option></select></label>
      </div>
      <Button type="submit" disabled={busy || selected.length < 2 || metrics.length < 1}>Compare published values</Button>
    </form>}
    {quotes && <p className="mt-4 text-sm text-muted">Quotes unavailable: {quotes.explanation}</p>}
    {companies.total < 2 && <p className="mt-4 text-sm text-muted">This view contains fewer than two published companies. A comparison requires at least two.</p>}
    {result && <div className="mt-6 space-y-5" aria-live="polite">
      <h4 className="font-semibold">Last submitted comparison</h4>
      {result.warnings.map((warning) => <p key={warning} className="text-sm">{warning}</p>)}
      <p className="text-sm">Selected basis: {result.selection.basis} · {result.selection.period.kind === 'DURATION' ? `${result.selection.period.start_date} to ${result.selection.period.end_date}` : result.selection.period.instant_date}. Active corpus {result.view.corpus_version_id}{result.view.as_of_date ? ` as of ${result.view.as_of_date}` : ''}.</p>
      <div className="overflow-x-auto rounded-lg border border-line bg-white"><table className="w-full text-left text-sm"><caption className="p-4 text-left font-semibold">Published values and exact unit normalization</caption><thead><tr><th scope="col" className="p-4">Metric</th>{result.companies.map((company) => <th scope="col" className="min-w-44 p-4" key={company.id}>{company.name}</th>)}</tr></thead><tbody>{result.rows.map((row) => <tr className="border-t border-line align-top" key={row.metric.id}><th scope="row" className="p-4">{row.metric.label}</th>{row.cells.map((cell) => <td key={cell.company_id} className="p-4"><p className="max-w-64 break-all font-semibold">{cell.normalized ? `${cell.normalized.value} ${cell.normalized.unit}` : 'Unavailable'}</p><p className="mt-2 text-xs">{cell.state.replaceAll('_', ' ')}</p><p className="mt-2 max-w-64 text-xs leading-5 text-muted">{cell.explanation}</p></td>)}</tr>)}</tbody></table></div>
      {result.rows.map((row) => <section key={row.metric.id} aria-label={`${row.metric.label} calculations`} className="rounded-lg border border-line bg-white p-4"><h4 className="font-semibold">{row.metric.label}: differences from {result.companies[0]?.name}</h4><ul className="mt-3 space-y-3">{row.differences.map((pair) => <li className="text-sm" key={pair.company_id}><p className="font-medium">{result.companies.find((company) => company.id === pair.company_id)?.name}</p><p className="mt-1 break-all">Difference: {pair.difference !== null ? `${pair.difference} ${pair.unit}` : 'Unavailable'}. Percentage difference: {pair.percentage_difference !== null ? `${pair.percentage_difference}%` : `Unavailable (${pair.percentage_state.replaceAll('_', ' ').toLowerCase()})`}.</p><p className="mt-1 text-xs text-muted">{pair.explanation}</p></li>)}</ul><p className="mt-4 text-xs leading-5 text-muted">Difference = {result.policy.difference_formula}. Percentage difference = {result.policy.percentage_formula}; positive baseline required, rounded to {result.policy.percentage_decimal_places} decimal places using {result.policy.percentage_rounding}. These comparisons do not imply a growth rate or recommendation.</p>
        {row.cells.map((cell) => <details className="mt-4 border-t border-line pt-3" key={cell.company_id}><summary className="cursor-pointer text-sm font-medium">Input disclosures: {result.companies.find((company) => company.id === cell.company_id)?.name} ({cell.inputs.length})</summary>{cell.inputs.map(({ observation }) => <article className="mt-3" key={observation.id}><blockquote className="whitespace-pre-wrap text-sm leading-6">{observation.raw_text}</blockquote><FinancialContext quantity={observation.quantity} /><p className="mt-2 break-all text-xs text-muted">Observation {observation.id} · filing {observation.filing_version_id} · source date {observation.source_published_on ?? 'unknown'}</p>{cell.normalized && <p className="mt-2 text-xs">Exact scale multiplier: {cell.normalized.multiplier}</p>}{inspect(observation)}</article>)}</details>)}
      </section>)}
    </div>}
  </section>
}
