import { useEffect, useState } from 'react'
import { ModuleApi } from './api'
import type { PortfolioAnalytics } from './generated'

export function Analytics({ api, account, version, companyName }: { api: ModuleApi; account: string; version: string; companyName: (identity: string) => string }) {
  const [result, setResult] = useState<PortfolioAnalytics | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    void api.read('analytics', `/v1/portfolio/analytics?portfolio_version_id=${encodeURIComponent(version)}`, controller.signal).then((value) => {
      if (value.account_id !== account || value.portfolio_version_id !== version) throw new Error('The ledger changed while loading analytics. Refresh the portfolio to synchronize.')
      if (!controller.signal.aborted) { setResult(value); setError('') }
    }).catch((failure: unknown) => { if (!controller.signal.aborted) { setResult(null); setError(failure instanceof Error ? failure.message : 'Ledger analytics are unavailable.') } })
    return () => controller.abort()
  }, [api, account, version])
  const summary = result?.summary
  return <section className="rounded-xl border border-line bg-white p-5" aria-labelledby="ledger-analytics-heading">
    <h3 id="ledger-analytics-heading" className="font-semibold">Ledger cash-flow analytics</h3>
    <p className="mt-2 text-sm text-muted">Cash flow tracks virtual money paid and received. It does not value open holdings. Market valuation remains unavailable.</p>
    {summary && <>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="text-muted">Executed / rejected orders</dt><dd>{summary.executed_orders} / {summary.rejected_orders}</dd></div>
        <div><dt className="text-muted">Net virtual cash flow</dt><dd>INR {summary.net_cash_flow}</dd></div>
        <div><dt className="text-muted">Virtual buy spend</dt><dd>INR {summary.buy_spend}</dd></div>
        <div><dt className="text-muted">Virtual sale proceeds</dt><dd>INR {summary.sale_proceeds}</dd></div>
      </dl>
      {result.companies.length > 0 && <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[32rem] text-left text-sm"><caption className="mb-3 text-left text-xs text-muted">Results use complete recorded company positions. A closed-position result is shown only after all shares have been sold.</caption><thead><tr><th className="p-2">Company</th><th className="p-2">Shares</th><th className="p-2">Net cash flow</th><th className="p-2">Closed-position result</th></tr></thead><tbody>{result.companies.map((item) => <tr key={item.company_id} className="border-t border-line"><td className="p-2">{companyName(item.company_id)}</td><td className="p-2">{item.quantity}</td><td className="p-2">INR {item.net_cash_flow}</td><td className="p-2">{item.closed_position_result === null ? 'Unavailable while shares remain' : `INR ${item.closed_position_result}`}</td></tr>)}</tbody></table></div>}
      <p className="mt-4 break-all text-xs text-muted">Based on {result.input_entry_ids.length} committed entries · portfolio version {result.portfolio_version_id}</p>
    </>}
    {result?.state === 'LEDGER_BUDGET_EXCEEDED' && <p role="status" className="mt-4 text-sm">The ledger exceeds the analytics budget. No partial totals are shown; cash and history remain available.</p>}
    {!result && !error && <p role="status" className="mt-4 text-sm">Loading replay-verified analytics…</p>}
    {error && <p role="alert" className="mt-4 text-sm">{error}</p>}
  </section>
}
