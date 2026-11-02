import { afterEach, describe, expect, it, vi } from 'vitest'
import fixture from './numerical-queue.fixture.json'
import { AdminApi } from './api'
import { canonical, checked, decode } from './wire'
import { queuedPacketMismatch } from './numericalQueueChecks'

const selection = { state: 'ALL', review: 'ALL', query: '', offset: 0, limit: 20 } as const
const signal = () => new AbortController().signal
const other = canonical('00000000-0000-4000-8000-000000000001')
afterEach(() => vi.unstubAllGlobals())

function selectedPacket() {
  const item = decode('numerical_queue', fixture.pages.unreviewed).items[0]!
  const confirmed = decode('numerical_queue', fixture.pages.confirmed).items[0]!
  const raw = Object.values(fixture.packets).find((value) => value.data.gate.id === item.gate.id)!
  const packet = decode('numerical_packet', raw)
  if (!confirmed.review) throw new Error('The authored fixture needs its recorded confirmation.')
  return { item, confirmed, packet, reviewed: { ...packet, review: confirmed.review } }
}

describe('historical numerical review queue contracts', () => {
  it('retains actual owned unreviewed, confirmed, rejected and empty pages without acceptance', () => {
    for (const page of Object.values(fixture.pages)) {
      const value = decode('numerical_queue', page)
      expect(value.scope).toBe('RETAINED_HISTORY_ONLY')
      for (const item of value.items) expect(item.gate.acceptance_eligible).toBe(false)
    }
    for (const packet of Object.values(fixture.packets)) expect(decode('numerical_packet', packet).binding.phrases.length).toBeGreaterThan(0)
    expect(decode('numerical_queue', fixture.pages.all).items.length).toBeGreaterThan(0)
    expect(decode('numerical_queue', fixture.pages.empty).items).toHaveLength(0)
  })

  it('allows a later recorded review to appear when opening an earlier unreviewed row', () => {
    const { item, confirmed, packet, reviewed } = selectedPacket()
    expect(queuedPacketMismatch(item, packet)).toBeNull()
    expect(queuedPacketMismatch(item, reviewed)).toBeNull()
    expect(queuedPacketMismatch(confirmed, reviewed)).toBeNull()
  })

  it('does not let a recorded review disappear on opening', () => {
    const { confirmed, packet } = selectedPacket()
    expect(queuedPacketMismatch(confirmed, packet)).toBe('REVIEW')
  })

  it('does not replace a recorded review actor or audit', () => {
    const { confirmed, reviewed } = selectedPacket()
    expect(queuedPacketMismatch(confirmed, { ...reviewed, review: { ...reviewed.review, auth_version: 42 } })).toBe('REVIEW')
  })

  it('keeps the selected source version and immutable gate exact', () => {
    const { item, packet } = selectedPacket()
    expect(queuedPacketMismatch({ ...item, filing_version_id: packet.gate.parse_version_id }, packet)).toBe('SOURCE')
    expect(queuedPacketMismatch({ ...item, gate: decode('numerical_queue', fixture.pages.rejected).items[0]!.gate }, packet)).toBe('SOURCE')
  })

  it.each(['duplicate', 'order', 'gate-check-order', 'gate-state', 'review-filter', 'state-filter', 'review-gate', 'review-evidence', 'review-note', 'acceptance', 'publication', 'scope', 'continuation', 'corpus'])('rejects corrupted %s', (mode) => {
    // Controlled two-row corruption case assembled from actual reviewed HTTP rows.
    const value = { ...structuredClone(fixture.pages.confirmed), data: { ...structuredClone(fixture.pages.confirmed.data), review_filter: 'ALL', items: structuredClone([fixture.pages.confirmed.data.items[0]!, fixture.pages.rejected.data.items[0]!]).sort((a, b) => a.gate.id.localeCompare(b.gate.id)) } }
    const item = value.data.items[0]!
    if (mode === 'duplicate') value.data.items.push(item)
    if (mode === 'order') value.data.items.reverse()
    if (mode === 'gate-check-order') item.gate.checks.reverse()
    if (mode === 'gate-state') item.gate.checks[0]!.state = 'FAIL'
    if (mode === 'review-filter') value.data.review_filter = 'UNREVIEWED'
    if (mode === 'state-filter') value.data.state_filter = 'QUARANTINED'
    if (mode === 'review-gate') item.review.request.gate_run_id = other
    if (mode === 'review-evidence') item.review.request.evidence_ids.pop()
    if (mode === 'review-note') item.review.request.note = '   '
    if (mode === 'acceptance') Object.assign(item.gate, { acceptance_eligible: true })
    if (mode === 'publication') Object.assign(item.review, { publishes_fact: true })
    if (mode === 'scope') value.data.scope = 'CURRENTLY_ACCEPTED'
    if (mode === 'continuation') value.data.has_more = true
    if (mode === 'corpus') Object.assign(value.meta.versions, { corpus_version_id: other })
    expect(() => decode('numerical_queue', value)).toThrow()
  })

  it.each([{ query: '\0' }, { query: 'x'.repeat(121) }, { offset: -1 }, { offset: 10001 }, { limit: 0 }, { limit: 21 }, { state: 'ACCEPTED' }, { review: 'APPROVE' }])('rejects invalid request filters %j', (change) => {
    expect(() => checked('numerical_queue_request', { ...selection, ...change })).toThrow()
  })

  it('encodes literal search and checks the exact requested queue page', async () => {
    const response = structuredClone(fixture.pages.all)
    const query = '<script>%_&company'
    response.data.query = query
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)))
    vi.stubGlobal('fetch', fetcher)
    const value = await new AdminApi('authored-test-token').numericalQueue({ ...selection, query }, signal())
    expect(value.query).toBe(query)
    const url = new URL(String(fetcher.mock.calls[0]![0]))
    expect(url.searchParams.get('query')).toBe(query)
    expect(url.searchParams.get('review')).toBe('ALL')
  })

  it.each(['state_filter', 'review_filter', 'query', 'offset', 'limit'])('refuses a self-consistent response for another %s', async (field) => {
    const response = structuredClone(fixture.pages.empty)
    response.data.query = ''
    if (field === 'state_filter') response.data.state_filter = 'QUARANTINED'
    if (field === 'review_filter') response.data.review_filter = 'ALL'
    if (field === 'query') response.data.query = 'other'
    if (field === 'offset') response.data.offset = 20
    if (field === 'limit') response.data.limit = 10
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(response))))
    await expect(new AdminApi('authored-test-token').numericalQueue({ ...selection, review: 'UNREVIEWED' }, signal())).rejects.toThrow()
  })
})
