import { afterEach, describe, expect, it, vi } from 'vitest'
import fixtures from './fixtures.generated.json'
import { checked, decode, PendingWrites, sameValue } from './wire'
import { AdminApi, AdminError } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('administrator exact review contracts', () => {
  it('keeps complete conditional source, all checks and an unpublished workspace', () => {
    const page = decode('review_page', fixtures.review_page)
    expect(page.items[0]?.draft.raw_text).toContain('subject to approvals')
    expect(page.items[0]?.result.checks).toHaveLength(16)
    expect(decode('queue', fixtures.queues.filings).published_corpus_id).toBeNull()
  })

  it.each(['parse', 'candidate', 'direction', 'text', 'checks', 'eligibility', 'extra'])('rejects a mismatched %s', (mode) => {
    const value = structuredClone(fixtures.review_page)
    const item = value.data.items[0]!
    if (mode === 'parse') value.data.parse_version_id = '00000000-0000-4000-8000-000000000001'
    if (mode === 'candidate') item.result.candidate_id = '00000000-0000-4000-8000-000000000001'
    if (mode === 'direction') item.draft.subject_entity_id = '00000000-0000-4000-8000-000000000001'
    if (mode === 'text') item.draft.raw_text = 'Unsupported conclusion'
    if (mode === 'checks') item.result.checks.pop()
    if (mode === 'eligibility') item.result.reviewer_eligible = false
    if (mode === 'extra') Object.assign(value, { accepted: true })
    expect(() => decode('review_page', value)).toThrow()
  })

  it('retains a prior final decision even when its audit differs', () => {
    const value = structuredClone(fixtures.review_page)
    const item = value.data.items[0]!
    const review = fixtures.manifest.data.new_acceptances[0]!.original_review.decision
    Object.assign(item, { review: { ...review, validation_run_id: '00000000-0000-4000-8000-000000000001' } })
    expect(decode('review_page', value).items[0]?.review?.id).toBe(review.id)
  })

  it('rejects caller-supplied authoritative fields', () => {
    expect(() => checked('publication_request', { idempotency_key: crypto.randomUUID(), parent_corpus_version_id: null, selections: [], accepted: true })).toThrow()
  })

  it('keeps a write identity across retries and changes it for a changed decision', () => {
    const item = fixtures.review_page.data.items[0]!
    const payload = { candidate_id: item.candidate.id, validation_run_id: fixtures.review_page.data.run_id, decision: 'APPROVE_FOR_PUBLICATION', review_note: 'Reviewed exact source.', supports: item.draft.supports }
    const pending = new PendingWrites()
    const first = pending.body('review_request', payload, 'id')
    expect(pending.body('review_request', payload, 'id').id).toBe(first.id)
    expect(pending.body('review_request', { ...payload, decision: 'REJECT' }, 'id').id).not.toBe(first.id)
    pending.clear()
    expect(pending.body('review_request', payload, 'id').id).not.toBe(first.id)
  })

  it('compares supported amendment payloads without depending on JSON key order', () => {
    expect(sameValue({ a: [{ b: 1, c: '1.00' }] }, { a: [{ c: '1.00', b: 1 }] })).toBe(true)
    expect(sameValue({ value: '1.00' }, { value: 1 })).toBe(false)
  })
})

describe('administrator transport', () => {
  it('uses form login, then a current-admin identity check and bearer reads', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'authored-token', token_type: 'bearer' })))
      .mockResolvedValueOnce(new Response(JSON.stringify(fixtures.identity)))
      .mockResolvedValueOnce(new Response(JSON.stringify(fixtures.queues.filings)))
    vi.stubGlobal('fetch', fetch)
    const api = await AdminApi.login('authored-admin', 'authored-password', new AbortController().signal)
    await api.queue('filings', 0, new AbortController().signal)
    const login = fetch.mock.calls[0]![1]!
    expect(login.headers).toEqual({ 'Content-Type': 'application/x-www-form-urlencoded' })
    if (!(login.body instanceof URLSearchParams)) throw new Error('Login must use form parameters')
    expect(login.body.get('username')).toBe('authored-admin')
    expect(fetch.mock.calls[1]![0]).toContain('/v1/auth/admin/me')
    expect(fetch.mock.calls[2]![1]?.headers).toEqual({ Authorization: 'Bearer authored-token' })
    expect(fetch.mock.calls.every(([url]) => typeof url === 'string' && !url.includes('authored-password'))).toBe(true)
  })

  it.each([401, 403])('marks revoked or denied access (%s) for private-state clearing', async (status) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status })))
    await expect(new AdminApi('authored-token').queue('filings', 0, new AbortController().signal)).rejects.toMatchObject({ auth: true })
  })

  it('keeps a conflict explicit and rejects a response for a different queue', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 409 })))
    await expect(new AdminApi('token').queue('filings', 0, new AbortController().signal)).rejects.toBeInstanceOf(AdminError)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(fixtures.queues.validations))))
    await expect(new AdminApi('token').queue('filings', 0, new AbortController().signal)).rejects.toThrow()
  })
})
