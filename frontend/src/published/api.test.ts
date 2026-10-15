import { describe, expect, it, vi } from 'vitest'
import { decode, PublishedApi, ReadError } from './api'
import fixtures from './fixtures.generated.json'

const corpus = fixtures.info.data.corpus_version_id
const options = { corpus, historical: false, asOf: '' }
const signal = (): AbortSignal => new AbortController().signal

describe('published read wire and version gates', () => {
  it('accepts every authored output contract and retains exact support', () => {
    expect(decode('info', fixtures.info).corpus_version_id).toBe(corpus)
    expect(decode('companies', fixtures.companies, corpus).total).toBe(1)
    expect(decode('facts', fixtures.facts, corpus).facts[0]?.observation.raw_text).toContain('subject to approvals')
    expect(decode('graph', fixtures.graph, corpus).edges).toHaveLength(0)
    expect(decode('evidence', fixtures.evidence, corpus).supports[0]?.quote).toContain('subject to approvals')
  })
  it('rejects a mixed corpus or mixed filing/parse envelope', () => {
    expect(() => decode('facts', fixtures.facts, '00000000-0000-4000-8000-000000000001')).toThrow(ReadError)
    const altered = structuredClone(fixtures.evidence)
    altered.meta.versions.parse_version_id = '00000000-0000-4000-8000-000000000001'
    expect(() => decode('evidence', altered, corpus)).toThrow(ReadError)
  })
  it('rejects malformed counts, extra response data and invalid source spans', () => {
    const malformed = structuredClone(fixtures.companies)
    malformed.data.total = -1
    expect(() => decode('companies', malformed)).toThrow(ReadError)
    expect(() => decode('info', { ...fixtures.info, secret: 'invalid' })).toThrow(ReadError)
    const evidence = structuredClone(fixtures.evidence)
    evidence.data.evidence.record.span.end++
    expect(() => decode('evidence', evidence)).toThrow()
  })
  it('pins every read and sends the in-memory bearer without cookies or redirects', async () => {
    const mock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(fixtures.facts)))
    vi.stubGlobal('fetch', mock)
    const api = new PublishedApi('authored-token')
    await api.facts(options, fixtures.facts.data.company.id, 0, signal())
    const call = mock.mock.calls[0]
    expect(call?.[0]).toContain(`corpus_version_id=${corpus}`)
    expect(call?.[1]).toMatchObject({ credentials: 'omit', redirect: 'error', cache: 'no-store', headers: { Authorization: 'Bearer authored-token' } })
    expect(typeof call?.[0]).toBe('string')
    expect(call?.[0]).not.toEqual(expect.stringContaining('authored-token'))
  })
  it('classifies revoked authorization so the UI can clear all private state', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 401 })))
    await expect(new PublishedApi('expired').current(signal())).rejects.toMatchObject({ auth: true })
  })
  it('rejects an active response when accepted history was explicitly requested', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(fixtures.facts))))
    await expect(new PublishedApi('token').facts({ ...options, historical: true }, fixtures.facts.data.company.id, 0, signal())).rejects.toThrow('history or date view')
  })
  it('refuses source bytes whose digest differs even with matching response headers', async () => {
    vi.stubGlobal('crypto', { subtle: { digest: vi.fn().mockResolvedValue(new ArrayBuffer(32)) } })
    const bytes = new TextEncoder().encode('%PDF-authored-but-wrong')
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response(bytes, { headers: { 'Content-Type': 'application/pdf', 'Content-Length': String(bytes.length), ETag: `"${fixtures.evidence.data.evidence.source_sha256}"`, 'X-Corpus-Version-ID': corpus } })))
    await expect(new PublishedApi('token').pdf(options, fixtures.evidence.data.observation_id, fixtures.evidence.data.evidence.source_sha256, signal())).rejects.toThrow('hash does not match')
  })
})
