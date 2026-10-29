import { afterEach, describe, expect, it, vi } from 'vitest'
import fixture from './numerical.fixture.json'
import { AdminApi } from './api'
import { checked, decode } from './wire'
import { checkNumericalAcceptance, checkNumericalCandidate, checkNumericalPreparation } from './numerical'

// Retained actual HTTP/build output over fictional engineering source declarations.
const snapshot = fixture.manifest.new_acceptances[0]!
const original = snapshot.accepted.candidate.preparation.proposed_input
const packetValue = () => structuredClone({ gate: original.gate, binding: original.proof, review: original.context_review })
const envelope = (data: unknown) => ({ data, meta: fixture.private_meta })
const packet = () => decode('numerical_packet', envelope(packetValue()))
const candidate = () => decode('numerical_candidate', envelope(snapshot.accepted.candidate))
const signal = () => new AbortController().signal
const other = '00000000-0000-4000-8000-000000000001'
afterEach(() => vi.unstubAllGlobals())

describe('numerical administrator source and context contracts', () => {
  it('retains every separate word, table/cell and exact decimal through publication', () => {
    const value = packet()
    expect(value.gate.evidence_ids).toHaveLength(51)
    expect(value.gate.quantity_proposal?.normalized_value).toBe('2500.20')
    expect(value.gate.quantity_proposal?.period.start_date).toBe('2023-04-01')
    expect(value.binding.phrases[0]?.words[0]?.evidence.span.quote).toBe('2,500.20')
    expect(decode('manifest', envelope(fixture.manifest)).new_acceptances).toHaveLength(1)
  })

  it.each(['gate-parse', 'source-hash', 'context', 'evidence', 'gate-order', 'gate-state', 'quantity', 'word-span', 'word-order', 'page', 'cell', 'table', 'review-gate', 'review-input', 'review-evidence', 'review-note'])('rejects inconsistent %s', (mode) => {
    const value = packetValue()
    if (mode === 'gate-parse') value.gate.parse_version_id = other
    if (mode === 'source-hash') value.binding.source_sha256 = 'e'.repeat(64)
    if (mode === 'context') value.gate.context_record_id = other
    if (mode === 'evidence') value.gate.evidence_ids.pop()
    if (mode === 'gate-order') value.gate.checks.reverse()
    if (mode === 'gate-state') value.gate.checks[0]!.state = 'REVIEW'
    if (mode === 'quantity') Object.assign(value.gate, { quantity_proposal: null })
    if (mode === 'word-span') value.binding.phrases[0]!.words[0]!.reference.end -= 1
    if (mode === 'word-order') value.binding.phrases[1]!.words[1]!.reference.word_index += 1
    if (mode === 'page') value.binding.phrases[1]!.words[1]!.evidence.source.page_id = other
    if (mode === 'cell') value.binding.cells[0]!.word_evidence_ids[0] = other
    if (mode === 'table') value.binding.cells[0]!.artifact_table_id = other
    if (mode === 'review-gate') value.review.request.gate_run_id = other
    if (mode === 'review-input') value.review.gate_input_sha256 = 'e'.repeat(64)
    if (mode === 'review-evidence') value.review.request.evidence_ids.pop()
    if (mode === 'review-note') value.review.request.note = '   '
    expect(() => decode('numerical_packet', envelope(value))).toThrow()
  })

  it('does not make a blocked source confirmable by retaining an earlier confirmation', () => {
    const value = packetValue()
    value.gate.state = 'REVIEW_REQUIRED'; value.gate.checks[0]!.state = 'REVIEW'
    expect(() => decode('numerical_packet', envelope(value))).toThrow()
    value.review.request.decision = 'REJECT'
    expect(decode('numerical_packet', envelope(value)).gate.state).toBe('REVIEW_REQUIRED')
  })

  it.each(['checks', 'state', 'proposal-gate', 'hash', 'configuration', 'quantity', 'review-hash', 'review-decision', 'policy', 'basis', 'period'])('rejects an invalid preparation %s', (mode) => {
    const value = structuredClone(snapshot.accepted.candidate.preparation)
    if (mode === 'checks') value.checks[0]!.state = 'REVIEW'
    if (mode === 'state') value.state = 'BLOCKED'
    if (mode === 'proposal-gate') value.proposed_input.gate_run_id = other
    if (mode === 'hash') value.proposed_input.gate_input_sha256 = 'e'.repeat(64)
    if (mode === 'configuration') value.proposed_input.configuration_sha256 = 'e'.repeat(64)
    if (mode === 'quantity') value.proposed_input.quantity.normalized_value = '9999.00'
    if (mode === 'review-hash') value.proposed_input.context_review.gate_result_sha256 = 'e'.repeat(64)
    if (mode === 'review-decision') value.proposed_input.context_review.request.decision = 'REJECT'
    if (mode === 'policy') value.proposed_input.policy.metric_id = other
    if (mode === 'basis') value.proposed_input.quantity.basis = 'UNKNOWN'
    if (mode === 'period') value.proposed_input.quantity.period.start_date = '2025-04-01'
    expect(() => decode('numerical_preparation', envelope(value))).toThrow()
  })

  it('rejects a ready snapshot substituted for a different displayed gate', () => {
    const value = checked('numerical_preparation', snapshot.accepted.candidate.preparation)
    const mixed = { ...packet(), gate: { ...packet().gate, id: checked('numerical_packet', packetValue()).binding.filing_id } }
    expect(() => checkNumericalPreparation(value, mixed)).toThrow()
    expect(() => checkNumericalCandidate(candidate(), mixed)).toThrow()
  })

  it.each(['candidate-id', 'prepared-id', 'accept-candidate', 'accept-evidence', 'accept-hash', 'accept-state', 'accept-check', 'accept-mandatory', 'reject-with-checks'])('rejects changed candidate or decision %s', (mode) => {
    const value = structuredClone(snapshot.accepted)
    if (mode === 'candidate-id') value.candidate.record.request.gate_run_id = other
    if (mode === 'prepared-id') value.candidate.record.request.prepared_input_id = other
    if (mode === 'accept-candidate') value.record.request.candidate_id = other
    if (mode === 'accept-evidence') value.record.request.evidence_ids.pop()
    if (mode === 'accept-hash') value.record.candidate_preparation_sha256 = 'e'.repeat(64)
    if (mode === 'accept-state') value.record.state = 'REJECTED'
    if (mode === 'accept-check') value.record.checks[0]!.state = 'FAIL'
    if (mode === 'accept-mandatory') value.record.mandatory_m1_validation_complete = false
    if (mode === 'reject-with-checks') { value.record.request.decision = 'REJECT'; value.record.state = 'REJECTED'; value.record.mandatory_m1_validation_complete = false }
    expect(() => decode('numerical_acceptance', envelope(value))).toThrow()
  })

  it('retains a real explicit rejection without claiming successful validation', () => {
    const value = structuredClone(snapshot.accepted)
    value.record.request.decision = 'REJECT'; value.record.state = 'REJECTED'; value.record.checks = []; value.record.mandatory_m1_validation_complete = false
    const result = decode('numerical_acceptance', envelope(value))
    checkNumericalAcceptance(result, candidate())
    expect(result.record.state).toBe('REJECTED')
  })

  it.each(['subject', 'metric', 'value', 'candidate-run', 'fresh-snapshot'])('rejects a changed publication audit %s even when observation copies agree', (mode) => {
    const value = structuredClone(fixture.manifest)
    const audit = value.new_acceptances[0]!
    for (const observation of [value.observations[0]!, audit.observation]) {
      if (mode === 'subject') observation.subject_entity_id = other
      if (mode === 'metric') observation.metric_id = other
      if (mode === 'value') observation.quantity.normalized_value = '9999.00'
      if (mode === 'candidate-run') observation.candidate_run_id = other
    }
    if (mode === 'fresh-snapshot') audit.fresh_preparation.configuration_sha256 = 'e'.repeat(64)
    expect(() => decode('manifest', envelope(value))).toThrow()
  })

  it('rejects a JSON number substituted for an authoritative decimal string', () => {
    const value = structuredClone(snapshot.accepted.candidate.preparation)
    Object.assign(value.proposed_input.quantity, { normalized_value: 2500.20 })
    expect(() => decode('numerical_preparation', envelope(value))).toThrow()
  })
})

describe('numerical administrator transport', () => {
  it('distinguishes a missing acceptance from storage failure', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(new Response('', { status: 404 })).mockResolvedValueOnce(new Response('', { status: 503 }))
    vi.stubGlobal('fetch', fetch)
    const api = new AdminApi('authored-token')
    expect(await api.numericalAcceptance(candidate(), signal())).toBeNull()
    await expect(api.numericalAcceptance(candidate(), signal())).rejects.toMatchObject({ auth: false, status: 503 })
    expect(fetch.mock.calls[0]?.[0]).toContain(`/candidates/${candidate().record.id}/acceptance`)
  })

  it.each([401, 403])('propagates current-admin denial %s for private-state clearing', async (status) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status })))
    await expect(new AdminApi('authored-token').numericalAcceptance(candidate(), signal())).rejects.toMatchObject({ auth: true })
  })

  it('rejects a valid response for a different selected gate or candidate', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(envelope(packetValue())))))
    await expect(new AdminApi('authored-token').numericalPacket(other, signal())).rejects.toThrow()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(envelope(snapshot.accepted.candidate)))))
    await expect(new AdminApi('authored-token').numericalCandidate(packet(), other, signal())).rejects.toThrow()
  })

  it('does not send a context override for an unresolved source', async () => {
    const value = { ...packet(), review: null, gate: { ...packet().gate, state: 'REVIEW_REQUIRED' as const } }
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    await expect(new AdminApi('authored-token').reviewNumerical(value, packet().review!.request, signal())).rejects.toThrow()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('posts exact backend IDs and rejects a changed candidate request in the response', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(new Response(JSON.stringify(envelope(snapshot.accepted.candidate))))
    vi.stubGlobal('fetch', fetch)
    const source = packet(); const value = candidate(); const api = new AdminApi('authored-token')
    expect(await api.createNumericalCandidate(source, value.preparation, value.record.request, signal())).toEqual(value)
    expect(fetch.mock.calls[0]?.[1]?.body).toBe(JSON.stringify(value.record.request))
    expect(fetch.mock.calls[0]?.[1]?.headers).toEqual({ Authorization: 'Bearer authored-token', 'Content-Type': 'application/json' })
    const body = { ...value.record.request, prepared_input_id: source.binding.id }
    await expect(api.createNumericalCandidate(source, value.preparation, body, signal())).rejects.toThrow()
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('rejects a changed submitted decision instead of clearing an uncertain write', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(envelope(snapshot.accepted)))))
    const body = { ...checked('numerical_acceptance', snapshot.accepted).record.request, note: 'A different explicit note.' }
    await expect(new AdminApi('authored-token').decideNumerical(candidate(), body, signal())).rejects.toThrow()
  })
})
