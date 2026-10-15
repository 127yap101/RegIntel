import type { QuantitativeValue } from './generated'

export function FinancialContext({ quantity }: { quantity: QuantitativeValue | null }) {
  if (!quantity) return null
  const fields = [
    ['Raw disclosure', [quantity.raw_value, quantity.raw_unit, quantity.raw_currency].filter((item) => item !== null).join(' ')],
    ['Normalized value', [quantity.normalized_value ?? 'Unavailable', quantity.normalized_unit, quantity.currency].filter((item) => item !== null).join(' ')],
    ['Period type', quantity.period.kind],
    ['Period label', quantity.period.raw_label ?? 'Unknown'],
    ['Period start', quantity.period.start_date ?? 'Unknown'],
    ['Period end', quantity.period.end_date ?? 'Unknown'],
    ['Instant date', quantity.period.instant_date ?? 'Unknown'],
    ['Reporting basis', quantity.basis],
    ['Basis label', quantity.raw_basis_label ?? 'Unknown'],
    ['Denominator', quantity.denominator ?? 'Unknown'],
    ['Stake kind', quantity.stake_kind ?? 'Unknown'],
    ['Ownership date', quantity.ownership_date ?? 'Unknown'],
  ] as const
  return <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">{fields.map(([label, value]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="break-words">{value}</dd></div>)}</dl>
}
