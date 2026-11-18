// Independently authored expected ratios for fixed-price engineering scenarios.
// No runtime quotes or authoritative financial calculations use this fixture.
import { cashOnlyValuation, fifoValuation } from './valuationFixtures.test-support'

type AuthoredValuation = ReturnType<typeof fifoValuation> | ReturnType<typeof cashOnlyValuation>
export function authoredMetrics(valuation: AuthoredValuation, simple: string | null, weights: readonly string[], sum: string | null = '100.000000', residual: string | null = '0.000000') {
  const available = valuation.state === 'AVAILABLE'
  const openingZero = valuation.cash_flow.opening_cash === '0.00'
  const totalZero = valuation.total_value === '0.00'
  return {
    schema_version: 'portfolio-snapshot-metrics-1', valuation,
    percentage_decimal_places: 6, rounding_mode: 'ROUND_HALF_EVEN', return_basis: 'SELECTED_LEDGER_AT_VALUATION_TIME',
    simple_return: {
      state: !available ? valuation.state : openingZero ? 'ZERO_OPENING_CASH' : 'AVAILABLE',
      numerator: available ? valuation.total_result : null,
      denominator: available ? valuation.cash_flow.opening_cash : null,
      percentage: available && !openingZero ? simple : null,
    },
    allocation: {
      state: !available ? valuation.state : totalZero ? 'ZERO_TOTAL_VALUE' : 'AVAILABLE',
      denominator: available ? valuation.total_value : null,
      entries: available && !totalZero ? [
        { kind: 'CASH', company_id: null as string | null, numerator: valuation.cash_flow.cash, percentage: weights[0] },
        ...valuation.positions.map((position, index) => ({ kind: 'HOLDING', company_id: position.cash_flow.company_id, numerator: position.market_value!, percentage: weights[index + 1] })),
      ] : [],
      percentage_sum: available && !totalZero ? sum : null,
      rounding_residual: available && !totalZero ? residual : null,
    },
  }
}

const expected = {
  opening: ['0.000000', '100.000000'],
  buy: ['0.030000', '99.950015', '0.049985'],
  purchases: ['0.045000', '99.875056', '0.124944'],
  partial: ['0.065000', '99.975016', '0.024984'],
  closed: ['0.055000', '100.000000'],
  reopened: ['0.091000', '99.950045', '0.049955'],
} as const

export function fifoMetrics(key: keyof typeof expected, priced = true) {
  const [simple, ...weights] = expected[key]
  return authoredMetrics(fifoValuation(key, priced), simple, weights)
}

export function cashOnlyMetrics(recorded = false) {
  return authoredMetrics(cashOnlyValuation(recorded), '0.000000', ['100.000000'])
}
