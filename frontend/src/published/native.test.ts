import { describe, expect, it } from 'vitest'
import { decode } from './api'
import { parseComparison, type ComparisonRequest } from '../analysis/wire'
import { decode as parseModule } from '../modules/api'
import wire from './native.fixture.json'
import context from '../modules/native-context.fixture.json'
import { parseContract } from '../contracts/runtime'

const facts = decode('facts', wire.facts)
const other = decode('companies', wire.companies).companies.find((company) => company.id === wire.request.company_ids[1])
if (!other || !facts.facts[0]) throw new Error('The authored native fixture lacks its selected companies or metric')
const request: ComparisonRequest = { corpus_version_id: facts.view.corpus_version_id, company_ids: [facts.company.id, other.id], metric_ids: [facts.facts[0].metric.id], period: parseContract('FinancialPeriod', wire.request.period), basis: 'CONSOLIDATED', as_of_date: null }

// Captured from the authored owned-PostgreSQL publication scenario. These are
// fictional engineering sources/decisions, not real financial review or prices.
describe('native numerical publication across module wire contracts', () => {
  it('retains complete M1 proof and the deterministic M2 result', () => {
    const facts = decode('facts', wire.facts)
    const observation = facts.facts[0]?.observation
    expect(observation && 'schema_version' in observation).toBe(true)
    expect(observation?.supports.length).toBeGreaterThan(16)
    expect(observation?.quantity?.normalized_value).toBe('2500.20')
    const comparison = parseComparison(wire.comparison, request)
    expect(comparison.rows[0]?.cells[0]?.state).toBe('AVAILABLE')
    expect(comparison.rows[0]?.cells[0]?.normalized?.value).toBe('2500200000.00')
    expect(parseModule('context', context).observation.id).toBe(observation?.id)
  })
  it('rejects a dropped M1 word even when the JSON remains structurally valid', () => {
    const altered = structuredClone(wire.facts)
    altered.data.facts[0]!.observation.supports.pop()
    expect(() => decode('facts', altered)).toThrow()
  })
  it('rejects altered native M2 page membership', () => {
    const altered = structuredClone(wire.comparison)
    const observation = altered.data.rows[0]!.cells[0]!.inputs[0]!.observation
    observation.proof.phrases[0]!.words[0]!.evidence.source.page_id = '00000000-0000-4000-8000-000000000001'
    expect(() => parseComparison(altered, request)).toThrow()
  })
  it('rejects M3 context missing part of the published proof', () => {
    const altered = structuredClone(context)
    altered.data.evidence.pop()
    expect(() => parseModule('context', altered)).toThrow()
  })
})
