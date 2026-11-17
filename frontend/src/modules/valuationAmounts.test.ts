import { describe, expect, it } from 'vitest'
import { decode, ModuleError } from './api'
import { envelope } from './fixtures.test-support'
import { cashOnlyValuation, fifoValuation, valuationQuoteVersion } from './valuationFixtures.test-support'
import { checkValuationSnapshot } from './valuationAmounts'
import fifo from './fifo.fixture.json'

function response(key: keyof typeof fifo.snapshots = 'partial', priced = true) {
  const data = structuredClone(fifoValuation(key, priced))
  return envelope(data, { portfolio_version_id: data.portfolio_version_id, quote_version_id: data.quote_version_ids[0] ?? null })
}

describe('source-linked virtual valuation', () => {
  it.each(['opening', 'buy', 'purchases', 'partial', 'closed', 'reopened'] as const)('preserves exact %s holdings, FIFO results and current source versions', (key) => {
    const value = decode('valuation', response(key))
    const account = decode('portfolio', fifo.snapshots[key].portfolio)
    expect(() => checkValuationSnapshot(value, account)).not.toThrow()
    expect(value.total_value).toEqual(fifoValuation(key).total_value)
    expect(value.evaluated_at).toBe('2026-10-23T06:00:00Z')
    if (value.positions.length) expect(value.quote_version_ids).toEqual([valuationQuoteVersion])
  })
  it('keeps held-position totals absent when the provider is unavailable', () => {
    const value = decode('valuation', response('partial', false))
    expect(value.state).toBe('QUOTES_UNAVAILABLE')
    expect(value.total_value).toBeNull()
    expect(value.positions[0]?.state).toBe('MISSING_QUOTE')
    expect(value.cash_flow?.realized_result).toBe('60.00')
  })
  it('values cash after a rejected unpriced order without inventing a quote', () => {
    const source = cashOnlyValuation(true)
    expect(decode('valuation', envelope(source, { portfolio_version_id: source.portfolio_version_id })).total_value).toBe('100000.00')
  })
  it.each(['total', 'numeric', 'missing_position', 'cost', 'quantity', 'quote_company', 'expired', 'source_versions', 'duplicates', 'meta', 'partial'])('rejects inconsistent %s valuation data', (change) => {
    const payload = structuredClone(response())
    const value = structuredClone(fifoValuation('partial'))
    payload.data = value
    if (change === 'total') Object.assign(value, { total_value: '100066.00' })
    if (change === 'numeric') Object.assign(value, { total_value: 100065 })
    if (change === 'missing_position') Object.assign(value, { positions: [] })
    if (change === 'cost') Object.assign(value.positions[0]!.cash_flow, { remaining_cost_basis: '21.00' })
    if (change === 'quantity') Object.assign(value.positions[0]!.cash_flow, { quantity: 2 })
    if (change === 'quote_company') Object.assign(value.positions[0]!.quote!, { company_id: valuationQuoteVersion })
    if (change === 'expired') Object.assign(value, { evaluated_at: '2026-10-23T06:01:00Z' })
    if (change === 'source_versions') Object.assign(value, { quote_version_ids: [] })
    if (change === 'duplicates') Object.assign(value, { input_entry_ids: [value.input_entry_ids[0], value.input_entry_ids[0], value.input_entry_ids[2]] })
    if (change === 'meta') payload.meta.versions.quote_version_id = null
    if (change === 'partial') Object.assign(value, { state: 'QUOTES_UNAVAILABLE' })
    expect(() => decode('valuation', payload)).toThrow(ModuleError)
  })
  it('keeps microsecond quote validity and equivalent timezone offsets exact', () => {
    const value = structuredClone(fifoValuation('partial'))
    Object.assign(value.positions[0]!.quote!, { observed_at: '2026-10-23T05:59:59.999999Z', expires_at: '2026-10-23T06:00:00.000001Z' })
    Object.assign(value, { evaluated_at: '2026-10-23T11:30:00+05:30' })
    const payload = envelope(value, { portfolio_version_id: value.portfolio_version_id, quote_version_id: valuationQuoteVersion })
    expect(decode('valuation', payload).state).toBe('AVAILABLE')
    Object.assign(value, { evaluated_at: '2026-10-23T06:00:00.000001Z' })
    expect(() => decode('valuation', payload)).toThrow(ModuleError)
  })
  it.each(['account', 'version', 'cash', 'holdings'])('rejects valuation from a different selected %s', (change) => {
    const account = structuredClone(decode('portfolio', fifo.snapshots.partial.portfolio))
    if (change === 'account') Object.assign(account, { account_id: valuationQuoteVersion })
    if (change === 'version') Object.assign(account, { portfolio_version_id: valuationQuoteVersion })
    if (change === 'cash') Object.assign(account.state, { cash: '1.00' })
    if (change === 'holdings') Object.assign(account.state, { holdings: [] })
    expect(() => checkValuationSnapshot(decode('valuation', response('partial')), account)).toThrow()
  })
})
