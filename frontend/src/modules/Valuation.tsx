import { useEffect, useState } from 'react'
import { ModuleApi } from './api'
import type { PortfolioAccount, PortfolioValuation, PositionValuation } from './generated'
import { checkValuationSnapshot } from './valuationAmounts'

const states: Record<PositionValuation['state'], string> = { AVAILABLE: 'Available', MISSING_QUOTE: 'Quote unavailable', WRONG_QUOTE: 'Quote belongs to another company', STALE_QUOTE: 'Quote outside its validity period', CONFLICTING_QUOTE: 'Conflicting quote identity' }

export function Valuation({ api, account, companyName }: { api: ModuleApi; account: PortfolioAccount; companyName: (identity: string) => string }) {
  const [response, setResponse] = useState<{ account: PortfolioAccount; result: PortfolioValuation | null; error: string } | null>(null)
  const result = response?.account === account ? response.result : null
  const error = response?.account === account ? response.error : ''
  useEffect(() => {
    const controller = new AbortController()
    void api.read('valuation', `/v1/portfolio/valuation?portfolio_version_id=${encodeURIComponent(account.portfolio_version_id)}`, controller.signal).then((value) => {
      checkValuationSnapshot(value, account)
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
