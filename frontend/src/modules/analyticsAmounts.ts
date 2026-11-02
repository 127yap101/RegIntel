import type { PortfolioAccount, PortfolioAnalytics } from './generated'

const fields = ['buy_spend', 'sale_proceeds', 'net_cash_flow', 'realized_cost_basis', 'remaining_cost_basis', 'realized_result'] as const
type AmountField = (typeof fields)[number]

function cents(value: string): bigint {
  const match = value.length <= 128 ? /^(-?)(0|[1-9]\d*)(?:\.(\d{1,2}))?$/u.exec(value) : null
  if (!match) throw new Error('Portfolio amounts require exact decimal currency values.')
  const amount = BigInt(match[2]!) * 100n + BigInt((match[3] ?? '').padEnd(2, '0'))
  return match[1] ? -amount : amount
}

function reconcile(value: Pick<NonNullable<PortfolioAnalytics['summary']>, AmountField>): Record<AmountField, bigint> {
  const amounts = Object.fromEntries(fields.map((field) => [field, cents(value[field])])) as Record<AmountField, bigint>
  if (amounts.buy_spend < 0n || amounts.sale_proceeds < 0n || amounts.realized_cost_basis < 0n || amounts.remaining_cost_basis < 0n || amounts.realized_cost_basis + amounts.remaining_cost_basis !== amounts.buy_spend || amounts.sale_proceeds - amounts.realized_cost_basis !== amounts.realized_result || amounts.sale_proceeds - amounts.buy_spend !== amounts.net_cash_flow) throw new Error('FIFO costs and cash-flow amounts do not reconcile.')
  return amounts
}

export function checkAnalyticsAmounts(value: PortfolioAnalytics): void {
  if (!value.summary) throw new Error('Available analytics require complete financial totals.')
  const summary = reconcile(value.summary)
  if (cents(value.summary.opening_cash) + summary.net_cash_flow !== cents(value.summary.cash)) throw new Error('Analytics cash does not reconcile to its opening balance.')
  const totals: Record<AmountField, bigint> = { buy_spend: 0n, sale_proceeds: 0n, net_cash_flow: 0n, realized_cost_basis: 0n, remaining_cost_basis: 0n, realized_result: 0n }
  let previous = ''
  for (const item of value.companies) {
    const amounts = reconcile(item)
    if (item.company_id <= previous || item.bought_quantity === 0 || item.bought_quantity - item.sold_quantity !== item.quantity || (item.quantity === 0) !== (amounts.remaining_cost_basis === 0n)) throw new Error('FIFO company membership or remaining lots differ.')
    if (item.closed_position_result !== null && (cents(item.closed_position_result) !== amounts.realized_result || cents(item.closed_position_result) !== amounts.net_cash_flow)) throw new Error('A closed-position result must match its realized result.')
    previous = item.company_id
    for (const field of fields) totals[field] += amounts[field]
  }
  if (fields.some((field) => totals[field] !== summary[field])) throw new Error('FIFO company amounts differ from portfolio totals.')
}

export function checkAnalyticsSnapshot(value: PortfolioAnalytics, account: PortfolioAccount): void {
  if (value.account_id !== account.account_id || value.portfolio_version_id !== account.portfolio_version_id || value.committed_orders !== account.committed_orders) throw new Error('Analytics differ from the selected portfolio version.')
  if (!value.summary) return
  if (cents(value.summary.cash) !== cents(account.state.cash)) throw new Error('Analytics cash differs from the selected virtual account.')
  const positions = value.companies.filter((item) => item.quantity > 0)
  if (positions.length !== account.state.holdings.length || positions.some((item, index) => item.company_id !== account.state.holdings[index]?.company_id || item.quantity !== account.state.holdings[index]?.quantity)) throw new Error('Analytics holdings differ from the selected virtual account.')
}
