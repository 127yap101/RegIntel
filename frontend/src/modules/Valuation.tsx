import { useEffect, useState } from 'react'
import { ModuleApi } from './api'
import type { PortfolioAccount, PortfolioSnapshotMetrics, PositionValuation } from './generated'
import { checkValuationSnapshot } from './valuationAmounts'

const states: Record<PositionValuation['state'], string> = { AVAILABLE: 'Available', MISSING_QUOTE: 'Quote unavailable', WRONG_QUOTE: 'Quote belongs to another company', STALE_QUOTE: 'Quote outside its validity period', CONFLICTING_QUOTE: 'Conflicting quote identity' }

export function Valuation({ api, account, companyName }: { api: ModuleApi; account: PortfolioAccount; companyName: (identity: string) => string }) {
  const [response, setResponse] = useState<{ account: PortfolioAccount; result: PortfolioSnapshotMetrics | null; error: string } | null>(null)
  const metrics = response?.account === account ? response.result : null
  const result = metrics?.valuation ?? null
  const error = response?.account === account ? response.error : ''
  useEffect(() => {
    const controller = new AbortController()
    void api.read('snapshot_metrics', `/v1/portfolio/metrics?portfolio_version_id=${encodeURIComponent(account.portfolio_version_id)}`, controller.signal).then((value) => {
      checkValuationSnapshot(value.valuation, account)
      if (!controller.signal.aborted) setResponse({ account, result: value, error: '' })
    }).catch((failure: unknown) => { if (!controller.signal.aborted) setResponse({ account, result: null, error: failure instanceof Error ? failure.message : 'Portfolio valuation is unavailable.' }) })
    return () => controller.abort()
  }, [api, account])
  return <section className="min-w-0 rounded-xl border border-line bg-white p-5" aria-labelledby="portfolio-valuation-heading">
    <h3 id="portfolio-valuation-heading" className="font-semibold">Virtual portfolio valuation</h3>
    <p className="mt-2 text-sm text-muted">Selected holdings are valued at the displayed server time. For an earlier portfolio version, this uses its holdings with current quote snapshots. Refresh the portfolio to request a new valuation.</p>
    {result && <>
      <p className="mt-3 text-sm">Valued at <time dateTime={result.evaluated_at}>{result.evaluated_at}</time> · INR</p>
      {result.state === 'AVAILABLE' && <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="text-muted">Holdings market value</dt><dd>INR {result.market_value}</dd></div>
        <div><dt className="text-muted">Total virtual value (cash + holdings)</dt><dd>INR {result.total_value}</dd></div>
        <div><dt className="text-muted">Unrealized result (FIFO)</dt><dd>INR {result.unrealized_result}</dd></div>
        <div><dt className="text-muted">Total virtual result</dt><dd>INR {result.total_result}</dd></div>
      </dl>}
      {result.state === 'QUOTES_UNAVAILABLE' && <p role="status" className="mt-4 text-sm">Valuation is unavailable because at least one holding lacks a valid quote. No partial portfolio totals are shown.</p>}
      {result.state === 'LEDGER_BUDGET_EXCEEDED' && <p role="status" className="mt-4 text-sm">The selected ledger exceeds the valuation budget. No partial valuation is shown.</p>}
      {metrics && <section aria-label="Snapshot return and allocation" className="mt-5 border-t border-line pt-4">
        <h4 className="font-semibold">Snapshot return and allocation</h4>
        <p className="mt-2 text-sm text-muted">These figures use the same holdings, prices and valuation time shown above. Simple return compares total virtual result with the opening virtual credit; it is not annualized.</p>
        {metrics.simple_return.state === 'AVAILABLE' && <div className="mt-3 text-sm"><p>Simple return: <strong>{metrics.simple_return.percentage}%</strong></p><p className="mt-1 text-muted">INR {metrics.simple_return.numerator} total result ÷ INR {metrics.simple_return.denominator} opening credit × 100.</p></div>}
        {metrics.simple_return.state === 'ZERO_OPENING_CASH' && <p role="status" className="mt-3 text-sm">Simple return is unavailable because the opening virtual credit is zero.</p>}
        {(metrics.simple_return.state === 'QUOTES_UNAVAILABLE' || metrics.simple_return.state === 'LEDGER_BUDGET_EXCEEDED') && <p className="mt-3 text-sm">Simple return and allocation are unavailable until the complete portfolio can be valued.</p>}
        {metrics.allocation.state === 'ZERO_TOTAL_VALUE' && <p role="status" className="mt-3 text-sm">Allocation is unavailable because total virtual value is zero.</p>}
        {metrics.allocation.state === 'AVAILABLE' && <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm">
          <caption className="mb-2 text-left">Cash and holding allocation · denominator INR {metrics.allocation.denominator} total virtual value</caption>
          <thead><tr><th className="p-2">Component</th><th className="p-2">Value (INR)</th><th className="p-2">Allocation</th></tr></thead>
          <tbody>{metrics.allocation.entries.map((entry) => <tr key={entry.company_id ?? 'cash'} className="border-t border-line"><td className="p-2">{entry.kind === 'CASH' ? 'Virtual cash' : companyName(entry.company_id!)}</td><td className="p-2">{entry.numerator}</td><td className="p-2">{entry.percentage}%</td></tr>)}</tbody>
        </table><p className="mt-2 text-xs text-muted">Displayed allocation sum: {metrics.allocation.percentage_sum}%. Rounding residual to 100%: {metrics.allocation.rounding_residual} percentage points.</p></div>}
        <p className="mt-3 text-xs text-muted">Percentages are rounded to six decimal places using half-even rounding. Exact currency inputs are retained; allocation weights are not adjusted to force a displayed sum of 100%.</p>
      </section>}
      {result.positions.length > 0 && <ul className="mt-4 space-y-3 text-sm">{result.positions.map((position) => <li key={position.cash_flow.company_id} className="rounded-lg border border-line p-3">
        <p>{companyName(position.cash_flow.company_id)} · {position.cash_flow.quantity} shares · {states[position.state]}</p>
        {position.state === 'AVAILABLE' && <p className="mt-2">Market value: INR {position.market_value} · Unrealized result: INR {position.unrealized_result}</p>}
        {position.quote && <details className="mt-2 break-all text-xs text-muted"><summary>Valuation quote source</summary><p className="mt-2">{position.quote.source} · {position.quote.source_kind === 'ENGINEERING_FIXTURE' ? 'Engineering fixture' : 'Reviewed dataset'}</p><p>Snapshot: {position.quote.id}</p><p>Quote version: {position.quote.quote_version_id}</p><p>Unit price: INR {position.quote.price}</p><p>Valid from {position.quote.observed_at} until {position.quote.expires_at}</p></details>}
      </li>)}</ul>}
      <p className="mt-4 break-all text-xs text-muted">Portfolio version: {result.portfolio_version_id} · {result.input_entry_ids.length} ledger inputs</p>
    </>}
    {!result && !error && <p role="status" className="mt-4 text-sm">Loading portfolio valuation…</p>}
    {error && <p role="alert" className="mt-4 text-sm">{error}</p>}
  </section>
}
