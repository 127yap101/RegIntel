import type { PortfolioSnapshotMetrics } from './generated'
import { cents } from './analyticsAmounts'
import { checkValuation } from './valuationAmounts'

const scale = 1000000n
const whole = 100n * scale

function requireMatch(condition: boolean): void {
  if (!condition) throw new Error('Snapshot return or allocation does not match its exact valuation inputs.')
}

function percentageUnits(value: string): bigint {
  const match = value.length <= 160 ? /^(-?)(0|[1-9]\d*)\.(\d{6})$/u.exec(value) : null
  if (!match) throw new Error('Snapshot percentages require exactly six decimal places.')
  const units = BigInt(match[2]!) * scale + BigInt(match[3]!)
  requireMatch(units !== 0n || match[1] !== '-')
  return match[1] ? -units : units
}

function expectedPercentage(numerator: string, denominator: string): bigint {
  const amount = cents(numerator), divisor = cents(denominator)
  requireMatch(divisor > 0n)
  const dividend = (amount < 0n ? -amount : amount) * whole
  let units = dividend / divisor
  const remainder = dividend % divisor
  if (remainder * 2n > divisor || remainder * 2n === divisor && units % 2n !== 0n) units += 1n
  return amount < 0n ? -units : units
}

export function checkSnapshotMetrics(value: PortfolioSnapshotMetrics): void {
  const { valuation, simple_return: simple, allocation } = value
  checkValuation(valuation)
  requireMatch(value.percentage_decimal_places === 6 && value.rounding_mode === 'ROUND_HALF_EVEN' && value.return_basis === 'SELECTED_LEDGER_AT_VALUATION_TIME')
  if (valuation.state !== 'AVAILABLE') {
    requireMatch(simple.state === valuation.state && allocation.state === valuation.state && simple.numerator === null && simple.denominator === null && simple.percentage === null && allocation.denominator === null && allocation.entries.length === 0 && allocation.percentage_sum === null && allocation.rounding_residual === null)
    return
  }
  const cash = valuation.cash_flow
  if (!cash || valuation.total_result === null || valuation.total_value === null) throw new Error('Snapshot metrics require a complete valuation.')
  requireMatch(simple.numerator === valuation.total_result && simple.denominator === cash.opening_cash)
  if (cents(cash.opening_cash) === 0n) requireMatch(simple.state === 'ZERO_OPENING_CASH' && simple.percentage === null)
  else requireMatch(simple.state === 'AVAILABLE' && simple.percentage !== null && percentageUnits(simple.percentage) === expectedPercentage(valuation.total_result, cash.opening_cash))
  requireMatch(allocation.denominator === valuation.total_value)
  if (cents(valuation.total_value) === 0n) {
    requireMatch(allocation.state === 'ZERO_TOTAL_VALUE' && allocation.entries.length === 0 && allocation.percentage_sum === null && allocation.rounding_residual === null)
    return
  }
  requireMatch(allocation.state === 'AVAILABLE' && allocation.entries.length === valuation.positions.length + 1)
  let sum = 0n
  for (const [index, entry] of allocation.entries.entries()) {
    const position = valuation.positions[index - 1]
    requireMatch(index === 0 ? entry.kind === 'CASH' && entry.company_id === null && entry.numerator === cash.cash : entry.kind === 'HOLDING' && position !== undefined && entry.company_id === position.cash_flow.company_id && entry.numerator === position.market_value)
    const units = percentageUnits(entry.percentage)
    requireMatch(units === expectedPercentage(entry.numerator, valuation.total_value))
    sum += units
  }
  requireMatch(allocation.percentage_sum !== null && percentageUnits(allocation.percentage_sum) === sum && allocation.rounding_residual !== null && percentageUnits(allocation.rounding_residual) === whole - sum)
}
