import { describe, expect, it } from 'vitest'
import parity from '../../../contracts/parity-vectors.json'
import { CONTRACT_NAMES } from './generated'
import type { ContractName } from './generated'
import { ContractValidationError, parseContract } from './runtime'

const names = new Set<string>(CONTRACT_NAMES)
const vectors = parity.vectors.map((vector) => {
  if (!names.has(vector.contract)) throw new Error('Unknown parity-vector contract.')
  return { ...vector, contract: vector.contract as ContractName }
})

function freezeDeep(value: unknown): unknown {
  if (typeof value === 'object' && value !== null) {
    for (const child of Object.values(value as Record<string, unknown>)) freezeDeep(child)
    Object.freeze(value)
  }
  return value
}

describe('shared wire contracts', () => {
  it.each(vectors)('$name matches the shared Python acceptance decision', (vector) => {
    if (vector.valid) {
      expect(parseContract(vector.contract, vector.payload)).toEqual(vector.payload)
    } else {
      expect(() => parseContract(vector.contract, vector.payload)).toThrow(ContractValidationError)
    }
  })

  it.each(vectors.filter((vector) => vector.valid))(
    '$name retains exact wire values and accepts deeply frozen input',
    (vector) => {
      const copy: unknown = JSON.parse(JSON.stringify(vector.payload))
      const before = JSON.stringify(copy)
      freezeDeep(copy)
      const result = parseContract(vector.contract, copy)
      expect(result).toBe(copy)
      expect(JSON.stringify(copy)).toBe(before)
      expect(JSON.stringify(result)).toBe(before)
    },
  )

  it('retains all 120 integer and fractional digits without numeric conversion', () => {
    const vector = vectors.find((candidate) => (
      candidate.valid && candidate.contract === 'QuantitativeValue'
    ))
    if (!vector) throw new Error('A valid shared quantitative vector is required.')
    const base = parseContract('QuantitativeValue', vector.payload)
    const exact = `${'9'.repeat(120)}.${'0'.repeat(119)}1`
    const quantity = freezeDeep({ ...base, normalized_value: exact })
    const parsed = parseContract('QuantitativeValue', quantity)
    expect(parsed.normalized_value).toBe(exact)
    expect(JSON.stringify(parsed)).toContain(`"normalized_value":"${exact}"`)
  })

  it('rejects unknown input without stripping properties or coercing values', () => {
    const vector = vectors.find((candidate) => (
      candidate.valid && candidate.contract === 'QuantitativeValue'
    ))
    if (!vector) throw new Error('A valid shared quantitative vector is required.')
    const base = parseContract('QuantitativeValue', vector.payload)
    const invalid = freezeDeep({ ...base, normalized_value: 17, unknown: 'preserve me' })
    const before = JSON.stringify(invalid)
    expect(() => parseContract('QuantitativeValue', invalid)).toThrow(ContractValidationError)
    expect(JSON.stringify(invalid)).toBe(before)
  })

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    'rejects a nonfinite geometry coordinate: %s',
    (coordinate) => {
      expect(() => parseContract('PdfRectangle', {
        x0: 0, y0: 0, x1: coordinate, y1: 1,
      })).toThrow(ContractValidationError)
    },
  )

  it('does not expose submitted values or validator diagnostics in errors', () => {
    const vector = vectors.find((candidate) => !candidate.valid)
    if (!vector) throw new Error('Shared invalid vectors are required.')
    try {
      parseContract(vector.contract, vector.payload)
      throw new Error('Invalid payload unexpectedly passed.')
    } catch (error) {
      expect(error).toBeInstanceOf(ContractValidationError)
      expect(String(error)).toBe('ContractValidationError: Invalid shared contract.')
      expect(error).not.toHaveProperty('errors')
      expect(error).not.toHaveProperty('cause')
    }
  })
})
