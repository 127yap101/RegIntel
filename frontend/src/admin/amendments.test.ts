import { afterEach, describe, expect, it, vi } from 'vitest'
import original from './numerical.fixture.json'
import amended from './amendment.fixture.json'
import { AdminApi } from './api'
import { checked, decode } from './wire'
import { amendmentContains, amendmentSpans, checkAmendmentSupport } from './amendments'

const proof = original.manifest.new_acceptances[0]!.accepted.candidate.preparation.proposed_input.proof
const words = proof.phrases.find((phrase) => phrase.role === 'issuer_header')!.words.slice(0, 3)
const ids = words.map((word) => word.evidence.id)
const raw = () => ({ schema_version: 'native-amendment-words-1', parse_version_id: proof.parse_version_id, spans: words.map(({ evidence }) => ({ evidence_id: evidence.id, start: 0, end: evidence.span.end, quote: evidence.span.quote })) })
const support = () => checked('native_amendment_words', raw())
afterEach(() => vi.unstubAllGlobals())

describe('separate native amendment word contracts', () => {
  it('retains source order, complete words and an explicit version without a combined quotation', () => {
    const value = support()
    expect(value.schema_version).toBe('native-amendment-words-1')
    expect(amendmentSpans(value).map((span) => span.quote)).toEqual(['Authored', 'Solar', 'Limited'])
    expect('quote' in value).toBe(false)
    expect(amendmentSpans(value.spans[0]!)).toEqual([value.spans[0]!])
  })

  it.each(['duplicate', 'partial', 'length', 'extra-quote', 'version', 'empty', 'large'])('rejects invalid native support %s', (mode) => {
    const value = raw()
    if (mode === 'duplicate') value.spans.push(value.spans[0]!)
    if (mode === 'partial') value.spans[0]!.start = 1
    if (mode === 'length') value.spans[0]!.end += 1
    if (mode === 'extra-quote') Object.assign(value, { quote: 'A fabricated combined quote' })
    if (mode === 'version') value.schema_version = 'unsupported'
    if (mode === 'empty') value.spans = []
    if (mode === 'large') value.spans = Array.from({ length: 129 }, () => value.spans[0]!)
    expect(() => checked('native_amendment_words', value)).toThrow()
  })

  it('does not treat sorted IDs or a different parse as an ordered subproof', () => {
    const whole = support(); const part = { ...whole, spans: whole.spans.slice(1) }
    expect(amendmentContains(whole, part)).toBe(true)
    expect(amendmentContains(whole, { ...part, spans: [...part.spans].reverse() })).toBe(false)
    const foreign = { ...part, parse_version_id: checked('native_amendment_words', { ...raw(), parse_version_id: '00000000-0000-4000-8000-000000000001' }).parse_version_id }
    expect(amendmentContains(whole, foreign)).toBe(false)
    expect(() => checkAmendmentSupport(whole, foreign.parse_version_id)).toThrow()
    expect(amendmentContains(whole.spans[0]!, part)).toBe(false)
  })

  it('retains the actually verified correction with current and historical observations', () => {
    const value = decode('manifest', { data: amended.manifest, meta: amended.meta })
    expect(value.lineages).toHaveLength(1)
    expect(value.effects[0]?.proposal.effect_type).toBe('CORRECT')
    expect(value.observations.length).toBeGreaterThan(value.active_observation_ids.length)
  })

  it.each(['parse', 'date-order', 'outside-date', 'duplicate', 'extra-quote'])('rejects a mixed native amendment manifest %s', (mode) => {
    const value = structuredClone(amended.manifest)
    const lineage = value.lineages[0]!.proposal; const effect = value.effects[0]!.proposal
    if (mode === 'parse') lineage.parent_identity.parse_version_id = lineage.child_identity.parse_version_id
    if (mode === 'date-order') effect.effective_date_support.spans.reverse()
    if (mode === 'outside-date') effect.effective_date_support.spans = lineage.child_identity.spans
    if (mode === 'duplicate') effect.supports[0]!.spans.push(effect.supports[0]!.spans[0]!)
    if (mode === 'extra-quote') Object.assign(effect.supports[0]!, { quote: 'Unsupported combined quote' })
    expect(() => decode('manifest', { data: value, meta: amended.meta })).toThrow()
  })
})

describe('native original-word loading', () => {
  function mock(mode?: string) {
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation((url) => {
      const path = typeof url === 'string' ? url : url instanceof URL ? url.href : url.url
      const index = ids.findIndex((id) => path.endsWith(id))
      const value = structuredClone(original.evidence)
      Object.assign(value.data, { record: structuredClone(words[index]!.evidence) })
      if (index === 1) {
        if (mode === 'page') value.data.record.source.page_id = '00000000-0000-4000-8000-000000000001'
        if (mode === 'hash') value.data.source_sha256 = 'e'.repeat(64)
        if (mode === 'configuration') value.data.processing_configuration_sha256 = 'e'.repeat(64)
        if (mode === 'identity') value.data.record.id = ids[0]!
        if (mode === 'partial') { value.data.record.span.start = 1; value.data.record.span.quote = value.data.record.span.quote.slice(1) }
      }
      return Promise.resolve(new Response(JSON.stringify(value)))
    })
    vi.stubGlobal('fetch', fetch); return fetch
  }

  it('fetches complete evidence and retains the operator order for backend verification', async () => {
    const fetch = mock(); const order = [...ids].reverse()
    const result = await new AdminApi('authored-token').amendmentWords(order, new AbortController().signal)
    expect(result.spans.map((span) => span.evidence_id)).toEqual(order)
    expect(result.spans.map((span) => span.quote)).toEqual(['Limited', 'Solar', 'Authored'])
    expect(fetch.mock.calls.every(([, request]) => request?.method === 'GET')).toBe(true)
  })

  it.each(['page', 'hash', 'configuration', 'identity', 'partial'])('rejects mixed original-word %s', async (mode) => {
    mock(mode)
    await expect(new AdminApi('authored-token').amendmentWords(ids, new AbortController().signal)).rejects.toThrow()
  })

  it.each([{ selected: [] }, { selected: [ids[0]!, ids[0]!] }, { selected: Array.from({ length: 129 }, () => ids[0]!) }])('refuses empty, duplicate or oversized input before any fetch', async ({ selected }) => {
    const fetch = mock()
    await expect(new AdminApi('authored-token').amendmentWords(selected, new AbortController().signal)).rejects.toThrow()
    expect(fetch).not.toHaveBeenCalled()
  })

  it.each([401, 403, 503])('does not resolve words after a failed response %s', async (status) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status })))
    await expect(new AdminApi('authored-token').amendmentWords(ids, new AbortController().signal)).rejects.toMatchObject({ auth: status !== 503 })
  })
})
