import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fixture from './numerical-applicability.fixture.json'
import base from './numerical.fixture.json'
import { AdminApi } from './api'
import { checked } from './wire'
import { applicabilityInspected, applicabilityInspectionPhrases, checkApplicabilityRequirements, checkApplicabilityReview } from './numericalApplicability'

const packet = () => checked('numerical_packet', structuredClone(fixture.packet))
const requirements = () => checked('numerical_applicability_requirements', structuredClone(fixture.requirements))
const review = () => checked('numerical_applicability_review', structuredClone(fixture.review))
const signal = () => new AbortController().signal
const envelope = (data: unknown) => ({ data, meta: base.private_meta })
const other = '00000000-0000-4000-8000-000000000001'
beforeEach(async () => { vi.stubGlobal('crypto', (await vi.importActual<{ webcrypto: Crypto }>('node:crypto')).webcrypto) })
afterEach(() => vi.unstubAllGlobals())

describe('applicability exact source membership', () => {
  it('verifies a backend-authored cross-page fixture and immutable receipt identity', async () => {
    await checkApplicabilityRequirements(requirements(), packet())
    await checkApplicabilityReview(review(), packet())
    expect(requirements().assertions).toHaveLength(7)
    expect(packet().gate.state).toBe('REVIEW_REQUIRED')
    expect(review().acceptance_eligible).toBe(false)
  })

  it.each(['gate', 'input', 'result', 'binding', 'value-cell', 'row-cell', 'period-cell', 'pages', 'word', 'word-order', 'assertion-order', 'duplicate', 'kind', 'eligibility'])('rejects changed %s membership before review', async (mode) => {
    const value = structuredClone(fixture.requirements)
    if (mode === 'gate') value.gate_run_id = other
    if (mode === 'input') value.gate_input_sha256 = 'b'.repeat(64)
    if (mode === 'result') value.gate_result_sha256 = 'b'.repeat(64)
    if (mode === 'binding') value.binding_id = other
    if (mode === 'value-cell') value.value_cell_id = other
    if (mode === 'row-cell') value.row_cell_id = other
    if (mode === 'period-cell') value.period_cell_id = other
    if (mode === 'pages') value.reviewed_page_indices.reverse()
    if (mode === 'word') value.assertions[0]!.evidence_ids[0] = other
    if (mode === 'word-order') value.assertions[0]!.evidence_ids.reverse()
    if (mode === 'assertion-order') value.assertions.reverse()
    if (mode === 'duplicate') value.assertions.push(value.assertions[0]!)
    if (mode === 'kind') value.assertions[0]!.kind = 'BASIS'
    if (mode === 'eligibility') Object.assign(value, { blockers: ['METRIC requires resolution before applicability review.'] })
    await expect(checkApplicabilityRequirements(checked('numerical_applicability_requirements', value), packet())).rejects.toThrow()
  })

  it.each(['note', 'review-id', 'configuration', 'gate'])('rejects a receipt with changed %s instead of claiming a saved decision', async (mode) => {
    const value = structuredClone(fixture.review)
    if (mode === 'note') value.request.note = 'A different review.'
    if (mode === 'review-id') value.id = other
    if (mode === 'configuration') value.configuration_sha256 = 'b'.repeat(64)
    if (mode === 'gate') value.request.gate_run_id = other
    await expect(checkApplicabilityReview(checked('numerical_applicability_review', value), packet())).rejects.toThrow()
  })

  it('requires every target cell and asserted phrase on both original source pages', () => {
    const value = packet(); const required = requirements()
    const phrases = applicabilityInspectionPhrases(value, required)
    const ids = phrases.map((phrase) => phrase.words[0]!.evidence.id)
    expect(applicabilityInspected(value, required, [])).toBe(false)
    expect(applicabilityInspected(value, required, ids)).toBe(true)
    for (let index = 0; index < ids.length; index += 1) expect(applicabilityInspected(value, required, ids.filter((_, offset) => offset !== index))).toBe(false)
  })
})

describe('applicability administrator transport', () => {
  it('sends the exact selection and reviewer note under the current token without an actor override', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(new Response(JSON.stringify(envelope(fixture.review))))
    vi.stubGlobal('fetch', fetch)
    const value = await new AdminApi('authored-token').reviewNumericalApplicability(packet(), requirements(), review().request, signal())
    expect(value).toEqual(review())
    expect(fetch.mock.calls[0]?.[1]?.body).toBe(JSON.stringify(review().request))
    expect(fetch.mock.calls[0]?.[1]?.headers).toEqual({ Authorization: 'Bearer authored-token', 'Content-Type': 'application/json' })
    expect(review().request).not.toHaveProperty('reviewed_by')
  })

  it('never submits applicability while canonical approval prerequisites remain blocked', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    const blocked = { ...requirements(), eligible: false, blockers: ['METRIC requires resolution before applicability review.'] }
    await expect(new AdminApi('authored-token').reviewNumericalApplicability(packet(), blocked, review().request, signal())).rejects.toThrow()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('separates missing history from unavailable storage', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(new Response('', { status: 404 })).mockResolvedValueOnce(new Response('', { status: 503 }))
    vi.stubGlobal('fetch', fetch)
    expect(await new AdminApi('authored-token').numericalApplicabilityReview(packet(), signal())).toBeNull()
    await expect(new AdminApi('authored-token').numericalApplicabilityReview(packet(), signal())).rejects.toMatchObject({ status: 503 })
  })

  it.each([401, 403])('propagates administrator access denial %s', async (status) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status })))
    await expect(new AdminApi('authored-token').numericalApplicabilityRequirements(packet(), signal())).rejects.toMatchObject({ auth: true })
  })

  it('rejects an otherwise valid receipt for a different submitted note', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(envelope(fixture.review)))))
    await expect(new AdminApi('authored-token').reviewNumericalApplicability(packet(), requirements(), { ...review().request, note: 'Different reviewer explanation.' }, signal())).rejects.toThrow('differs from the submitted review')
  })

  it('explicitly reruns the current source and attestation without confirming or accepting', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(new Response(JSON.stringify(envelope(fixture.resolved))))
    vi.stubGlobal('fetch', fetch)
    const resolved = await new AdminApi('authored-token').runNumericalApplicability(packet(), review(), signal())
    expect(resolved.gate.state).toBe('READY_FOR_REVIEW')
    expect(resolved.review).toBeNull()
    expect(fetch.mock.calls[0]?.[0]).toContain(`/gates/${packet().gate.id}/applicability/gate`)
    expect(fetch.mock.calls[0]?.[1]?.body).toBe('{}')
  })

  it.each(['base-gate', 'review', 'quantity', 'pass-check'])('rejects rerun %s substitution instead of navigating to a different gate', async (mode) => {
    const value = structuredClone(fixture.resolved)
    if (mode === 'base-gate') value.base_gate_run_id = other
    if (mode === 'review') value.applicability_review_id = other
    if (mode === 'quantity') value.packet.gate.quantity_proposal.normalized_value = '9000.00'
    if (mode === 'pass-check') value.packet.gate.checks.find((check) => check.code === 'SOURCE')!.message = 'A substituted passing source check.'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(envelope(value)))))
    await expect(new AdminApi('authored-token').runNumericalApplicability(packet(), review(), signal())).rejects.toThrow()
  })
})
