// Authored fixed-price engineering scenarios. These are not runtime market quotes.
import fifo from './fifo.fixture.json' with { type: 'json' }
import { analytics } from './fixtures.test-support'

export const valuationQuoteVersion = '00000000-0000-4000-8000-000000000095'
const expected = {
  opening: ['0.00', '100000.00', '0.00', '0.00'],
  buy: ['50.00', '100030.00', '30.00', '30.00'],
  purchases: ['125.00', '100045.00', '45.00', '45.00'],
  partial: ['25.00', '100065.00', '5.00', '65.00'],
  closed: ['0.00', '100055.00', '0.00', '55.00'],
  reopened: ['50.00', '100091.00', '36.00', '91.00'],
} as const

export function fifoValuation(key: keyof typeof fifo.snapshots, priced = true) {
  const selected = fifo.snapshots[key].analytics.data
  const positions = selected.companies.filter((company) => company.quantity > 0)
  const available = priced || positions.length === 0
  const totals = expected[key]
  const value = {
    account_id: selected.account_id, portfolio_version_id: selected.portfolio_version_id,
    evaluated_at: '2026-10-23T06:00:00Z', currency: 'INR', state: available ? 'AVAILABLE' : 'QUOTES_UNAVAILABLE',
    committed_orders: selected.committed_orders, cost_basis_method: 'FIFO',
    input_entry_ids: selected.input_entry_ids, corpus_version_ids: selected.corpus_version_ids,
    execution_quote_version_ids: selected.quote_version_ids, quote_version_ids: priced && positions.length ? [valuationQuoteVersion] : [],
    cash_flow: selected.summary,
    positions: positions.map((company) => ({ cash_flow: company, state: priced ? 'AVAILABLE' : 'MISSING_QUOTE', quote: priced ? {
      id: '00000000-0000-4000-8000-000000000096', quote_version_id: valuationQuoteVersion, company_id: company.company_id,
      price: '25.00', currency: 'INR', observed_at: '2026-10-23T05:59:00Z', expires_at: '2026-10-23T06:01:00Z',
      source: 'Authored valuation fixture <script>untrusted text</script>', source_kind: 'ENGINEERING_FIXTURE',
    } : null, market_value: priced ? totals[0] : null, unrealized_result: priced ? totals[2] : null })),
    market_value: available ? totals[0] : null, total_value: available ? totals[1] : null,
    unrealized_result: available ? totals[2] : null, total_result: available ? totals[3] : null,
  }
  return value
}

export function cashOnlyValuation(recorded = false) {
  const source = analytics(recorded)
  const value = {
    account_id: source.account_id, portfolio_version_id: source.portfolio_version_id,
    evaluated_at: '2026-10-24T06:00:00Z', currency: 'INR', state: 'AVAILABLE',
    committed_orders: source.committed_orders, cost_basis_method: 'FIFO', input_entry_ids: source.input_entry_ids,
    corpus_version_ids: source.corpus_version_ids, execution_quote_version_ids: [], quote_version_ids: [],
    cash_flow: source.summary, positions: [], market_value: '0.00', total_value: '100000.00', unrealized_result: '0.00', total_result: '0.00',
  }
  return value
}
