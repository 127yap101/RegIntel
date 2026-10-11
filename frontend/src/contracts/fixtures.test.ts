import { describe, expect, it } from 'vitest'
import fixtures from './fixtures.generated.json'
import { CONTRACT_NAMES } from './generated'
import type { ContractName } from './generated'
import { ContractValidationError, parseContract } from './runtime'

interface FixtureCase {
  readonly name: string
  readonly category: string
  readonly source_aliases: readonly string[]
  readonly contract_name: string | null
  readonly payload: unknown
  readonly structurally_valid: boolean | null
  readonly future_expectation: string
  readonly reason: string
}

const cases: readonly FixtureCase[] = fixtures.cases
const names = new Set<string>(CONTRACT_NAMES)
const contractCases = cases.flatMap((fixture) => {
  if (fixture.contract_name === null) return []
  if (!names.has(fixture.contract_name)) throw new Error('Unknown fixture contract.')
  if (fixture.payload === null || fixture.structurally_valid === null) {
    throw new Error('A contract fixture requires a payload and structural expectation.')
  }
  return [{ ...fixture, contract: fixture.contract_name as ContractName }]
})

function freezeDeep(value: unknown): unknown {
  if (typeof value === 'object' && value !== null) {
    for (const child of Object.values(value as Record<string, unknown>)) freezeDeep(child)
    Object.freeze(value)
  }
  return value
}

/**
 * future_expectation and reason are authored scenario data, not implementation
 * under test. These tests exercise current shared wire structure only; they do
 * not establish M1 evidence/context gates or runtime model behavior.
 */
describe('synthetic adversarial fixture wire parity', () => {
  it('identifies the fixture source as synthetic', () => {
    expect(fixtures.fixture_version).toBe('1.0.0')
    expect(fixtures.synthetic).toBe(true)
    expect(cases.length).toBeGreaterThan(0)
    expect(contractCases.length).toBeGreaterThan(0)
  })

  it.each(contractCases)('$name matches its authored structural validity', (fixture) => {
    const copy: unknown = JSON.parse(JSON.stringify(fixture.payload))
    const before = JSON.stringify(copy)
    freezeDeep(copy)
    if (fixture.structurally_valid) {
      const parsed = parseContract(fixture.contract, copy)
      expect(parsed).toBe(copy)
      expect(parsed).toEqual(fixture.payload)
      expect(JSON.stringify(parsed)).toBe(before)
    } else {
      expect(() => parseContract(fixture.contract, copy)).toThrow(ContractValidationError)
    }
    expect(JSON.stringify(copy)).toBe(before)
  })

  it.each(cases.filter((fixture) => fixture.contract_name === null))(
    '$name carries authored runtime expectations without a wire payload',
    (fixture) => {
      // Null runtime scenarios deliberately never call the contract validator.
      expect(fixture.payload).toBeNull()
      expect(fixture.structurally_valid).toBeNull()
    },
  )

  it.each(contractCases.filter((fixture) => (
    fixture.structurally_valid && fixture.contract === 'QuantitativeValue'
  )))('$name preserves exact decimal strings and raw values', (fixture) => {
    const input = parseContract('QuantitativeValue', freezeDeep(fixture.payload))
    const copy: unknown = JSON.parse(JSON.stringify(input))
    const parsed = parseContract('QuantitativeValue', freezeDeep(copy))
    expect(parsed.raw_value).toBe(input.raw_value)
    expect(parsed.normalized_value).toBe(input.normalized_value)
    if (parsed.normalized_value !== null) {
      expect(typeof parsed.normalized_value).toBe('string')
    }
    expect(parsed.raw_unit).toBe(input.raw_unit)
    expect(parsed.raw_currency).toBe(input.raw_currency)
    expect(parsed.raw_basis_label).toBe(input.raw_basis_label)
    expect(parsed.period.raw_label).toBe(input.period.raw_label)
  })
})
