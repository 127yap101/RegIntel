import { describe, expect, it, vi } from 'vitest'
import { answerRequest, parseAnswer } from './wire'
import fixtures from './fixtures.generated.json'
import { PublishedApi } from '../published/api'

const options = { corpus: fixtures.answer.data.retrieval.view.corpus_version_id, historical: false, asOf: '' }
const request = answerRequest(options, { question: 'What initial public offering is proposed?', arm: 'B3' })

describe('exact extractive answer wire boundary', () => {
  it('accepts authored exact citations and conditions', () => {
    const result = parseAnswer(fixtures.answer, options, request)
    expect(result.claims[0]?.text).toContain('subject to approvals')
    expect(result.claims[0]?.citations[0]?.page_index).toBe(0)
  })
  it.each(['corpus', 'historical', 'arm', 'budget', 'filter'])('rejects mixed %s scope', (change) => {
    const result = structuredClone(fixtures.answer)
    if (change === 'corpus') result.data.retrieval.view.corpus_version_id = '00000000-0000-4000-8000-000000000001'
    if (change === 'historical') result.data.retrieval.view.historical = true
    if (change === 'arm') result.data.retrieval.trace.arm = 'B0'
    if (change === 'budget') result.data.retrieval.trace.context_tokens = 2049
    if (change === 'filter') Object.assign(result.data.retrieval.trace.filters, { company_id: '00000000-0000-4000-8000-000000000001' })
    expect(() => parseAnswer(result, options, request)).toThrow()
  })
  it.each(['quote', 'evidence', 'filing', 'claim'])('rejects modified %s support', (change) => {
    const result = structuredClone(fixtures.answer)
    const citation = result.data.retrieval.hits[0]?.citations[0]
    if (!citation) throw new Error('Authored fixture citation missing')
    if (change === 'quote') citation.span.quote = 'Unsupported'
    if (change === 'evidence') citation.span.evidence_id = '00000000-0000-4000-8000-000000000001'
    if (change === 'filing') citation.filing_version_id = '00000000-0000-4000-8000-000000000001'
    if (change === 'claim' && result.data.claims[0]) result.data.claims[0].text = 'A guaranteed IPO has already occurred.'
    expect(() => parseAnswer(result, options, request)).toThrow()
  })
  it('rejects a claim attached to unavailable date state', () => {
    const result = structuredClone(fixtures.answer)
    result.data.retrieval.state = 'TEMPORAL_SUPPORT_UNAVAILABLE'
    result.data.retrieval.view.state = 'TEMPORAL_SUPPORT_UNAVAILABLE'
    expect(() => parseAnswer(result, options, request)).toThrow()
  })
  it('sends JSON with in-memory authorization and pinned view', async () => {
    const mock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(fixtures.answer)))
    vi.stubGlobal('fetch', mock)
    await new PublishedApi('authored-private-token').answer(options, { question: request.question, arm: 'B3' }, new AbortController().signal)
    const call = mock.mock.calls[0]
    expect(call?.[0]).toBe('http://127.0.0.1:8000/v1/answers')
    expect(call?.[1]).toMatchObject({ method: 'POST', credentials: 'omit', redirect: 'error', cache: 'no-store', headers: { Authorization: 'Bearer authored-private-token', 'Content-Type': 'application/json' } })
    const body = call?.[1]?.body
    if (typeof body !== 'string') throw new Error('Expected a JSON body')
    expect(JSON.parse(body)).toEqual(request)
  })
  it('classifies answer auth expiry for private state clearing', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 401 })))
    await expect(new PublishedApi('expired').answer(options, { question: request.question, arm: 'B3' }, new AbortController().signal)).rejects.toMatchObject({ auth: true })
  })
})
