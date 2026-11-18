import { describe, expect, it } from 'vitest'
import { decode, ModuleError } from './api'
import { envelope, ids } from './fixtures.test-support'
import { authoredMetrics, cashOnlyMetrics, fifoMetrics } from './snapshotMetricsFixtures.test-support'
import { cashOnlyValuation, fifoValuation } from './valuationFixtures.test-support'

function response(value = fifoMetrics('partial')) {
  return envelope(value, { portfolio_version_id: value.valuation.portfolio_version_id, quote_version_id: value.valuation.quote_version_ids[0] ?? null })
}

// Authored cash-only closing snapshots for exact rounding boundaries, not market data.
function closedResult(opening: string, cash: string, proceeds: string, result: string) {
  const value = structuredClone(fifoValuation('closed'))
  Object.assign(value.cash_flow, { opening_cash: opening, cash, sale_proceeds: proceeds, net_cash_flow: result, realized_result: result })
  Object.assign(value, { total_value: cash, total_result: result })
  return value
}

describe('source-linked snapshot return and allocation', () => {
  it.each(['opening', 'buy', 'purchases', 'partial', 'closed', 'reopened'] as const)('keeps %s return and allocation on one selected valuation', (key) => {
    const source = fifoMetrics(key)
    const value = decode('snapshot_metrics', response(source))
    expect(value.valuation).toEqual(source.valuation)
    expect(value.simple_return).toEqual(source.simple_return)
    expect(value.allocation).toEqual(source.allocation)
  })

  it('values cash and its full allocation after a rejected order without requiring quotes', () => {
    const value = decode('snapshot_metrics', response(cashOnlyMetrics(true)))
    expect(value.simple_return.percentage).toBe('0.000000')
    expect(value.allocation.entries).toEqual([{ kind: 'CASH', company_id: null, numerator: '100000.00', percentage: '100.000000' }])
  })

  it('withholds every percentage when even one holding lacks a quote', () => {
    const value = decode('snapshot_metrics', response(fifoMetrics('partial', false)))
    expect(value.simple_return).toEqual({ state: 'QUOTES_UNAVAILABLE', numerator: null, denominator: null, percentage: null })
    expect(value.allocation).toEqual({ state: 'QUOTES_UNAVAILABLE', denominator: null, entries: [], percentage_sum: null, rounding_residual: null })
  })

  it('preserves the explicit ledger budget state without partial metrics', () => {
    const source = fifoMetrics('partial', false)
    Object.assign(source.valuation, { state: 'LEDGER_BUDGET_EXCEEDED', cash_flow: null, positions: [], input_entry_ids: [], corpus_version_ids: [], execution_quote_version_ids: [], quote_version_ids: [] })
    source.simple_return.state = 'LEDGER_BUDGET_EXCEEDED'; source.allocation.state = 'LEDGER_BUDGET_EXCEEDED'
    expect(decode('snapshot_metrics', response(source)).simple_return.state).toBe('LEDGER_BUDGET_EXCEEDED')
  })

  it('keeps both zero-denominator states explicit on an empty zero-credit account', () => {
    const valuation = structuredClone(cashOnlyValuation())
    Object.assign(valuation.cash_flow, { cash: '0.00', opening_cash: '0.00' })
    valuation.total_value = '0.00'
    const value = decode('snapshot_metrics', response(authoredMetrics(valuation, null, [])))
    expect(value.simple_return).toEqual({ state: 'ZERO_OPENING_CASH', numerator: '0.00', denominator: '0.00', percentage: null })
    expect(value.allocation).toEqual({ state: 'ZERO_TOTAL_VALUE', denominator: '0.00', entries: [], percentage_sum: null, rounding_residual: null })
  })

  it('can show a complete-loss return while a zero total prevents allocation', () => {
    const source = authoredMetrics(closedResult('55.00', '0.00', '25.00', '-55.00'), '-100.000000', [])
    const value = decode('snapshot_metrics', response(source))
    expect(value.simple_return.percentage).toBe('-100.000000')
    expect(value.allocation.state).toBe('ZERO_TOTAL_VALUE')
  })

  it.each([
    ['2000000.01', '80.01', '0.01', '0.000000'],
    ['2000000.03', '80.03', '0.03', '0.000002'],
    ['1999999.99', '79.99', '-0.01', '0.000000'],
    ['1999999.97', '79.97', '-0.03', '-0.000002'],
  ])('checks half-even rounding at a signed exact midpoint (%s)', (cash, proceeds, result, percentage) => {
    const source = authoredMetrics(closedResult('2000000.00', cash, proceeds, result), percentage, ['100.000000'])
    expect(decode('snapshot_metrics', response(source)).simple_return.percentage).toBe(percentage)
    source.simple_return.percentage = result.startsWith('-') ? '-0.000001' : '0.000001'
    expect(() => decode('snapshot_metrics', response(source))).toThrow(ModuleError)
  })

  it.each([
    { total: '3.00', spend: '2.00', net: '-2.00', second: '1.00', weights: ['33.333333', '33.333333', '33.333333'], sum: '99.999999', residual: '0.000001' },
    { total: '6.00', spend: '5.00', net: '-5.00', second: '4.00', weights: ['16.666667', '16.666667', '66.666667'], sum: '100.000001', residual: '-0.000001' },
  ])('retains the signed $residual residual instead of forcing weights to total 100%', ({ total, spend, net, second, weights, sum, residual }) => {
    const valuation = structuredClone(fifoValuation('purchases'))
    Object.assign(valuation.cash_flow, { opening_cash: total, cash: '1.00', buy_spend: spend, net_cash_flow: net, remaining_cost_basis: spend })
    const template = valuation.positions[0]!
    valuation.positions = ['00000000-0000-4000-8000-000000000091', '00000000-0000-4000-8000-000000000092'].map((company, index) => {
      const position = structuredClone(template)
      const amount = index === 0 ? '1.00' : second
      Object.assign(position.cash_flow, { company_id: company, bought_quantity: 1, quantity: 1, buy_spend: amount, net_cash_flow: `-${amount}`, remaining_cost_basis: amount })
      Object.assign(position.quote!, { id: `00000000-0000-4000-8000-00000000009${index + 3}`, company_id: company, price: amount })
      Object.assign(position, { market_value: amount, unrealized_result: '0.00' })
      return position
    })
    Object.assign(valuation, { market_value: spend, total_value: total, unrealized_result: '0.00', total_result: '0.00' })
    const source = authoredMetrics(valuation, '0.000000', weights, sum, residual)
    expect(decode('snapshot_metrics', response(source)).allocation.rounding_residual).toBe(residual)
    source.allocation.entries[2]!.percentage = '33.333334'
    source.allocation.percentage_sum = '100.000000'; source.allocation.rounding_residual = '0.000000'
    expect(() => decode('snapshot_metrics', response(source))).toThrow(ModuleError)
  })

  it.each(['numerator', 'denominator', 'percentage', 'numeric', 'precision', 'signed_zero', 'allocation_denominator', 'component', 'company', 'order', 'extra', 'sum', 'residual', 'rounding', 'state', 'nested_total', 'version', 'quote_version', 'corpus_version'])('rejects altered %s inputs or results', (change) => {
    const source = structuredClone(fifoMetrics('partial'))
    const payload = response(source)
    if (change === 'numerator') source.simple_return.numerator = '66.00'
    if (change === 'denominator') source.simple_return.denominator = '100001.00'
    if (change === 'percentage') source.simple_return.percentage = '0.066000'
    if (change === 'numeric') Object.assign(source.simple_return, { percentage: 0.065 })
    if (change === 'precision') source.simple_return.percentage = '0.06500'
    if (change === 'signed_zero') source.allocation.rounding_residual = '-0.000000'
    if (change === 'allocation_denominator') source.allocation.denominator = '100066.00'
    if (change === 'component') source.allocation.entries[0]!.numerator = '100041.00'
    if (change === 'company') source.allocation.entries[1]!.company_id = ids.account
    if (change === 'order') source.allocation.entries.reverse()
    if (change === 'extra') source.allocation.entries.push(source.allocation.entries[1]!)
    if (change === 'sum') source.allocation.percentage_sum = '99.999999'
    if (change === 'residual') source.allocation.rounding_residual = '0.000001'
    if (change === 'rounding') source.rounding_mode = 'ROUND_HALF_UP'
    if (change === 'state') source.simple_return.state = 'ZERO_OPENING_CASH'
    if (change === 'nested_total') Object.assign(source.valuation, { total_value: '100066.00' })
    if (change === 'version') Object.assign(payload.meta.versions, { portfolio_version_id: ids.account })
    if (change === 'quote_version') payload.meta.versions.quote_version_id = null
    if (change === 'corpus_version') Object.assign(payload.meta.versions, { corpus_version_id: ids.account })
    expect(() => decode('snapshot_metrics', payload)).toThrow(ModuleError)
  })

  it('rejects a partial allocation even if no total valuation is available', () => {
    const source = fifoMetrics('partial', false)
    source.allocation.entries = cashOnlyMetrics().allocation.entries
    expect(() => decode('snapshot_metrics', response(source))).toThrow(ModuleError)
  })
})
