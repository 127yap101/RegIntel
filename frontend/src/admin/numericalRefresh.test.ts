import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fixture from './numerical.fixture.json'
import { AdminApi } from './api'
import { checked } from './wire'
import { checkNumericalRefresh, numericalRefreshRequest } from './numericalRefresh'

const source = fixture.manifest.new_acceptances[0]!.accepted.candidate.preparation.proposed_input
const packet = () => checked('numerical_packet', structuredClone({ gate: source.gate, binding: source.proof, review: null }))
const other = '00000000-0000-4000-8000-000000000001'
beforeEach(async () => { vi.stubGlobal('crypto', (await vi.importActual<{ webcrypto: Crypto }>('node:crypto')).webcrypto) })
afterEach(() => vi.unstubAllGlobals())

async function response() {
  const original = packet()
  const request = await numericalRefreshRequest(original)
  const value = checked('numerical_refresh', { schema_version: 'numerical-refresh-result-1', request: structuredClone(request), previous_context_record_id: original.gate.context_record_id, context_changed: false, gate_changed: false, packet: structuredClone(original), acceptance_eligible: false, mandatory_m1_validation_complete: false, publishes_fact: false })
  return { original, request, value }
}

describe('numerical prerequisite refresh', () => {
  it('binds the request to the existing backend result hash and preserves unchanged checks', async () => {
    const { original, request, value } = await response()
    expect(request.gate_result_sha256).toBe(source.context_review.gate_result_sha256)
    await checkNumericalRefresh(value, original, request)
  })

  it.each(['request', 'old-context', 'context-flag', 'gate-flag', 'parse', 'word', 'cell', 'unchanged-result', 'review'])('rejects altered %s before displaying a refreshed gate', async (kind) => {
    const { original, request, value } = await response()
    if (kind === 'request') Object.assign(value.request, { gate_input_sha256: 'b'.repeat(64) })
    if (kind === 'old-context') Object.assign(value, { previous_context_record_id: other })
    if (kind === 'context-flag') Object.assign(value, { context_changed: true })
    if (kind === 'gate-flag') Object.assign(value, { gate_changed: true })
    if (kind === 'parse') { Object.assign(value.packet.gate, { parse_version_id: other }); Object.assign(value.packet.binding, { parse_version_id: other }) }
    if (kind === 'word') Object.assign(value.packet.binding.phrases[0]!.words[0]!.evidence.span, { quote: 'changed' })
    if (kind === 'cell') Object.assign(value.packet.binding.cells[0]!, { column_index: value.packet.binding.cells[0]!.column_index + 1 })
    if (kind === 'unchanged-result') Object.assign(value.packet.gate.checks[0]!, { message: 'A changed check' })
    if (kind === 'review') Object.assign(value.packet, { review: checked('numerical_review', { ...source.context_review, request: { ...source.context_review.request, gate_run_id: other } }) })
    await expect(checkNumericalRefresh(value, original, request)).rejects.toThrow()
  })

  it('posts only a verified historical selection and rejects published metadata', async () => {
    const { original, request, value } = await response()
    const fetch = vi.fn().mockResolvedValueOnce(Response.json({ data: value, meta: fixture.private_meta }))
    vi.stubGlobal('fetch', fetch)
    const api = new AdminApi('authored-admin-token', 'http://localhost')
    expect(await api.refreshNumerical(original, request, new AbortController().signal)).toEqual(value)
    const [url, options] = fetch.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`http://localhost/v1/admin/numerical/gates/${original.gate.id}/refresh`)
    if (typeof options.body !== 'string') throw new Error('Expected a serialized refresh request')
    expect(JSON.parse(options.body)).toEqual(request)
    const mismatchedRequest = checked('numerical_refresh_request', { ...request, gate_run_id: other })
    await expect(api.refreshNumerical(original, mismatchedRequest, new AbortController().signal)).rejects.toThrow()
    expect(fetch).toHaveBeenCalledTimes(1)
    fetch.mockResolvedValueOnce(Response.json({ data: value, meta: { ...fixture.private_meta, versions: { ...fixture.private_meta.versions, corpus_version_id: other } } }))
    await expect(api.refreshNumerical(original, request, new AbortController().signal)).rejects.toThrow()
  })
})
