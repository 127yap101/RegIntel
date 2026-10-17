import { describe, expect, it, vi } from 'vitest'
import { PublishedApi } from '../published/api'
import { comparisonRequest, parseComparison, parseQuotes } from './wire'
import fixtures from './fixtures.generated.json'

const options = { corpus: fixtures.request.corpus_version_id, historical: false, asOf: '' }
const input = { companies: fixtures.request.company_ids, metrics: fixtures.request.metric_ids, period: { kind: 'DURATION' as const, start_date: '2025-04-01', end_date: '2026-03-31', instant_date: null, raw_label: null }, basis: 'CONSOLIDATED' as const }
const request = comparisonRequest(options, input)

describe('M2 version, input and exact decimal wire boundary', () => {
  it('retains exact source inputs, base values and disclosed formulas', () => {
    const result = parseComparison(fixtures.comparison, request)
    expect(result.rows[0]?.differences[0]?.difference).toBe('25000000.00')
    expect(result.rows[0]?.differences[0]?.percentage_difference).toBe('20.000000')
    expect(result.rows[0]?.cells[0]?.inputs[0]?.observation.quantity?.normalized_value).toBe('12.50')
    expect(result.policy.percentage_rounding).toBe('ROUND_HALF_EVEN')
  })
  it.each(['corpus', 'history', 'asof', 'basis', 'company', 'metric', 'period', 'rounding'])('rejects a mixed %s response', (mode) => {
    const value = structuredClone(fixtures.comparison)
    if (mode === 'corpus') value.meta.versions.corpus_version_id = '00000000-0000-4000-8000-000000000001'
    if (mode === 'history') value.data.view.historical = true
    if (mode === 'asof') Object.assign(value.data.view, { as_of_date: '2026-01-01' })
    if (mode === 'basis') value.data.selection.basis = 'STANDALONE'
    if (mode === 'company') value.data.companies.reverse()
    if (mode === 'metric') value.data.rows[0]!.metric.id = '00000000-0000-4000-8000-000000000001'
    if (mode === 'period') value.data.selection.period.start_date = '2024-04-01'
    if (mode === 'rounding') value.data.policy.percentage_decimal_places = 2
    expect(() => parseComparison(value, request)).toThrow()
  })
  it.each(['company', 'metric', 'basis', 'span', 'evidence', 'float', 'unavailable', 'temporal', 'pair'])('rejects modified %s inputs', (mode) => {
    const value = structuredClone(fixtures.comparison)
    const row = value.data.rows[0]!
    const cell = row.cells[0]!
    const observation = cell.inputs[0]!.observation
    if (mode === 'company') observation.subject_entity_id = '00000000-0000-4000-8000-000000000001'
    if (mode === 'metric') observation.metric_id = '00000000-0000-4000-8000-000000000001'
    if (mode === 'basis') observation.quantity.basis = 'STANDALONE'
    if (mode === 'span') observation.supports[0]!.quote += ' Unsupported'
    if (mode === 'evidence') observation.quantity.evidence_ids[0] = '00000000-0000-4000-8000-000000000001'
    if (mode === 'float') Object.assign(cell.normalized, { value: 125000000 })
    if (mode === 'unavailable') cell.state = 'MISSING'
    if (mode === 'temporal') value.data.view.state = 'TEMPORAL_SUPPORT_UNAVAILABLE'
    if (mode === 'pair') row.differences[0]!.input_observation_ids.reverse()
    expect(() => parseComparison(value, request)).toThrow()
  })
  it('rejects duplicate or historical selections', () => {
    expect(() => comparisonRequest(options, { ...input, companies: [input.companies[0]!, input.companies[0]!] })).toThrow()
    expect(() => comparisonRequest({ ...options, historical: true }, input)).toThrow()
  })
  it('distinguishes percentage points from a relative percentage result', () => {
    const value = structuredClone(fixtures.comparison)
    const row = value.data.rows[0]!
    row.cells.forEach((cell, index) => {
      const amount = index === 0 ? '12.00' : '15.00'
      const observation = cell.inputs[0]!.observation
      const quote = `Authored percentage disclosure: ${amount}%.`
      observation.raw_text = quote
      observation.supports[0]!.quote = quote
      observation.supports[0]!.end = observation.supports[0]!.start + quote.length
      observation.context_supports = []
      Object.assign(observation.quantity, { raw_value: amount, normalized_value: amount, raw_unit: '%', normalized_unit: '%', raw_currency: null, currency: null })
      Object.assign(cell.normalized, { value: amount, unit: '%', currency: null, multiplier: '1' })
    })
    Object.assign(row.differences[0]!, { difference: '3.00', unit: 'percentage points', currency: null, percentage_difference: '25.000000' })
    expect(parseComparison(value, request).rows[0]?.differences[0]?.unit).toBe('percentage points')
    row.differences[0]!.unit = '%'
    expect(() => parseComparison(value, request)).toThrow()
  })
  it('represents unavailable quotes without a price or version', () => {
    expect(parseQuotes(fixtures.quotes)).toMatchObject({ state: 'UNAVAILABLE', quotes: [], quote_version_id: null })
    const value = structuredClone(fixtures.quotes)
    Object.assign(value.data, { price: '1.00' })
    expect(() => parseQuotes(value)).toThrow()
    expect(() => parseQuotes({ data: {}, meta: fixtures.quotes.meta })).toThrow()
  })
  it('sends pinned JSON and keeps the token in memory', async () => {
    const mock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(fixtures.comparison)))
    vi.stubGlobal('fetch', mock)
    await new PublishedApi('authored-private-token').compare(options, input, new AbortController().signal)
    expect(mock.mock.calls[0]?.[0]).toBe('http://127.0.0.1:8000/v1/compare')
    expect(mock.mock.calls[0]?.[1]).toMatchObject({ method: 'POST', credentials: 'omit', redirect: 'error', cache: 'no-store', headers: { Authorization: 'Bearer authored-private-token', 'Content-Type': 'application/json' } })
    const body = mock.mock.calls[0]?.[1]?.body
    if (typeof body !== 'string') throw new Error('Expected an exact JSON comparison body')
    expect(JSON.parse(body)).toEqual(request)
  })
  it('classifies expired comparison and quote sessions for state clearing', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 401 })))
    const api = new PublishedApi('expired')
    await expect(api.compare(options, input, new AbortController().signal)).rejects.toMatchObject({ auth: true })
    await expect(api.quotes(new AbortController().signal)).rejects.toMatchObject({ auth: true })
  })
})
