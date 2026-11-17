import type { PortfolioAccount, PortfolioValuation, PositionValuation } from './generated'
import { cents, reconcile } from './analyticsAmounts'

function requireMatch(condition: boolean): void {
  if (!condition) throw new Error('The valuation sources or financial totals do not reconcile.')
}

function canonicalIds(values: readonly string[]): void {
  requireMatch(values.every((value, index) => index === 0 || value > values[index - 1]!))
}

function instant(value: string): bigint {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/u.exec(value)
  if (!match) throw new Error('The valuation timestamp is invalid.')
  const milliseconds = Date.parse(`${match[1]}${match[3]}`)
  if (!Number.isSafeInteger(milliseconds)) throw new Error('The valuation timestamp is invalid.')
  return BigInt(milliseconds) * 1000n + BigInt((match[2] ?? '').padEnd(6, '0'))
}

function quoteState(position: PositionValuation, at: bigint, duplicate: ReadonlySet<string>): PositionValuation['state'] {
  const quote = position.quote
  if (!quote) return 'MISSING_QUOTE'
  requireMatch(cents(quote.price) > 0n && cents(quote.price) <= 9999999999999999n && instant(quote.expires_at) > instant(quote.observed_at))
  if (duplicate.has(quote.id)) return 'CONFLICTING_QUOTE'
  if (quote.company_id !== position.cash_flow.company_id) return 'WRONG_QUOTE'
  if (at < instant(quote.observed_at) || at >= instant(quote.expires_at)) return 'STALE_QUOTE'
  return 'AVAILABLE'
}

export function checkValuation(value: PortfolioValuation): void {
  const totals = [value.market_value, value.total_value, value.unrealized_result, value.total_result]
  const sources = [value.input_entry_ids, value.corpus_version_ids, value.execution_quote_version_ids, value.quote_version_ids]
  const at = instant(value.evaluated_at)
  if (value.state === 'LEDGER_BUDGET_EXCEEDED') {
    requireMatch(value.cash_flow === null && !value.positions.length && sources.every((ids) => !ids.length) && totals.every((item) => item === null))
    return
  }
  const cash = value.cash_flow
  if (!cash) throw new Error('Valuation requires complete ledger cash flow.')
  requireMatch(value.input_entry_ids.length === value.committed_orders && new Set(value.input_entry_ids).size === value.input_entry_ids.length && (value.input_entry_ids.at(-1) ?? value.account_id) === value.portfolio_version_id && cash.executed_orders + cash.rejected_orders === value.committed_orders)
  for (const ids of sources.slice(1)) canonicalIds(ids)
  canonicalIds(value.positions.map((position) => position.cash_flow.company_id))
  const cashAmounts = reconcile(cash)
  requireMatch(cents(cash.opening_cash) >= 0n && cents(cash.cash) >= 0n && cents(cash.opening_cash) + cashAmounts.net_cash_flow === cents(cash.cash))
  const seen = new Set<string>(), duplicate = new Set<string>()
  const quoteVersions = new Set<string>()
  for (const position of value.positions) if (position.quote) {
    if (seen.has(position.quote.id)) duplicate.add(position.quote.id)
    seen.add(position.quote.id); quoteVersions.add(position.quote.quote_version_id)
  }
  requireMatch([...quoteVersions].sort().join(',') === value.quote_version_ids.join(','))
  let remaining = 0n, market = 0n
  for (const position of value.positions) {
    const company = position.cash_flow
    const amounts = reconcile(company)
    requireMatch(company.position_state === 'OPEN' && company.closed_position_result === null && company.quantity > 0 && company.quantity <= 1000000 && company.bought_quantity - company.sold_quantity === company.quantity && amounts.remaining_cost_basis > 0n)
    remaining += amounts.remaining_cost_basis
    requireMatch(position.state === quoteState(position, at, duplicate))
    if (position.state === 'AVAILABLE' && position.quote) {
      const amount = cents(position.quote.price) * BigInt(company.quantity)
      requireMatch(position.market_value !== null && cents(position.market_value) === amount && position.unrealized_result !== null && cents(position.unrealized_result) === amount - amounts.remaining_cost_basis)
      market += amount
    } else requireMatch(position.market_value === null && position.unrealized_result === null)
  }
  requireMatch(remaining === cashAmounts.remaining_cost_basis)
  const available = value.positions.every((position) => position.state === 'AVAILABLE')
  requireMatch((value.state === 'AVAILABLE') === available)
  if (!available) { requireMatch(totals.every((item) => item === null)); return }
  const total = cents(cash.cash) + market, unrealized = market - remaining
  requireMatch(value.market_value !== null && cents(value.market_value) === market && value.total_value !== null && cents(value.total_value) === total && value.unrealized_result !== null && cents(value.unrealized_result) === unrealized && value.total_result !== null && cents(value.total_result) === total - cents(cash.opening_cash) && cents(value.total_result) === unrealized + cashAmounts.realized_result)
}

export function checkValuationSnapshot(value: PortfolioValuation, account: PortfolioAccount): void {
  requireMatch(value.account_id === account.account_id && value.portfolio_version_id === account.portfolio_version_id && value.committed_orders === account.committed_orders)
  if (!value.cash_flow) return
  requireMatch(cents(value.cash_flow.cash) === cents(account.state.cash))
  requireMatch(value.positions.length === account.state.holdings.length && value.positions.every((position, index) => position.cash_flow.company_id === account.state.holdings[index]?.company_id && position.cash_flow.quantity === account.state.holdings[index]?.quantity))
}
