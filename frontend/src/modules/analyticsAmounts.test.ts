import { describe, expect, it } from 'vitest'
import fixture from './fifo.fixture.json'
import { decode, ModuleError } from './api'
import { checkAnalyticsSnapshot } from './analyticsAmounts'

describe('exact FIFO analytics response checks', () => {
  it('retains actual owned HTTP partial, closed and reopened results separately from cash flow', () => {
    const partial = decode('analytics', fixture.snapshots.partial.analytics)
    expect(partial.summary?.realized_result).toBe('60.00')
    expect(partial.summary?.remaining_cost_basis).toBe('20.00')
    expect(partial.summary?.net_cash_flow).toBe('40.00')
    expect(partial.companies[0]?.closed_position_result).toBeNull()
    const closed = decode('analytics', fixture.snapshots.closed.analytics)
    expect(closed.companies[0]?.closed_position_result).toBe('55.00')
    const reopened = decode('analytics', fixture.snapshots.reopened.analytics)
    expect(reopened.summary?.realized_result).toBe('55.00')
    expect(reopened.summary?.remaining_cost_basis).toBe('14.00')
    expect(reopened.companies[0]?.closed_position_result).toBeNull()
  })

  it.each(['allocated', 'remaining', 'result', 'negative', 'subcent', 'policy', 'company', 'aggregate', 'cash'])('rejects corrupted %s without producing derived totals', (change) => {
    const value = structuredClone(fixture.snapshots.partial.analytics)
    const company = value.data.companies[0]!
    if (change === 'allocated') company.realized_cost_basis = '61.00'
    if (change === 'remaining') company.remaining_cost_basis = '21.00'
    if (change === 'result') company.realized_result = '61.00'
    if (change === 'negative') company.remaining_cost_basis = '-1.00'
    if (change === 'subcent') company.realized_cost_basis = '60.001'
    if (change === 'policy') value.data.cost_basis_method = 'UNKNOWN'
    if (change === 'company') value.data.companies.push(company)
    if (change === 'cash') value.data.summary.cash = '100041.00'
    if (change === 'aggregate') Object.assign(value.data.summary, { buy_spend: '81.00', remaining_cost_basis: '21.00', net_cash_flow: '39.00', cash: '100039.00' })
    expect(() => decode('analytics', value)).toThrow(ModuleError)
  })

  it('checks a one-cent result above the safe floating-point integer range exactly', () => {
    // Authored high-range response, separate from the captured fixed-price scenario.
    const value = structuredClone(fixture.snapshots.closed.analytics)
    const amounts = { buy_spend: '90071992547409.93', sale_proceeds: '90071992547409.94', net_cash_flow: '0.01', realized_cost_basis: '90071992547409.93', remaining_cost_basis: '0.00', realized_result: '0.01' }
    Object.assign(value.data.summary, amounts, { opening_cash: '99999999999999.00', cash: '99999999999999.01' })
    Object.assign(value.data.companies[0]!, amounts, { closed_position_result: '0.01' })
    expect(decode('analytics', value).summary?.realized_result).toBe('0.01')
    value.data.summary.realized_result = '0.02'
    expect(() => decode('analytics', value)).toThrow(ModuleError)
  })

  it('matches a selected account, its cash and every remaining holding', () => {
    expect(() => checkAnalyticsSnapshot(decode('analytics', fixture.snapshots.partial.analytics), decode('portfolio', fixture.snapshots.partial.portfolio))).not.toThrow()
  })

  it.each(['owner', 'version', 'count', 'cash', 'quantity', 'company', 'missing'])('rejects analytics from a different account %s', (change) => {
    const response = structuredClone(fixture.snapshots.partial.portfolio)
    const account = response.data
    if (change === 'owner') account.account_id = fixture.snapshots.closed.portfolio.data.portfolio_version_id
    if (change === 'version') account.portfolio_version_id = fixture.snapshots.closed.portfolio.data.portfolio_version_id
    if (change === 'count') account.committed_orders += 1
    if (change === 'cash') account.state.cash = '100040.01'
    if (change === 'quantity') account.state.holdings[0]!.quantity = 2
    if (change === 'company') account.state.holdings[0]!.company_id = fixture.snapshots.closed.portfolio.data.portfolio_version_id
    if (change === 'missing') account.state.holdings = []
    response.meta.versions.portfolio_version_id = account.portfolio_version_id
    const selected = decode('portfolio', response)
    expect(() => checkAnalyticsSnapshot(decode('analytics', fixture.snapshots.partial.analytics), selected)).toThrow()
  })
})
