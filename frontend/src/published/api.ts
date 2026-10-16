import Ajv2020 from 'ajv/dist/2020'
import addFormats from 'ajv-formats'
import type { ValidateFunction } from 'ajv'
import { getApiBaseUrl } from '../api/health'
import { parseContract } from '../contracts/runtime'
import schema from './schema.json'
import { answerRequest, parseAnswer } from '../retrieval/wire'
import type { AnswerInput, AnswerResult } from '../retrieval/wire'
import type { RetrievalRequest } from '../retrieval/generated'
import type { CompanyGraph, CompanyPage, FactPage, PublishedEvidence, ViewInfo } from './generated'

export type { CompanyGraph, CompanyPage, FactPage, PublishedEvidence, ViewInfo } from './generated'
export interface ReadOptions { corpus: string; historical: boolean; asOf: string }
interface Wire { info: ViewInfo; companies: CompanyPage; facts: FactPage; graph: CompanyGraph; evidence: PublishedEvidence }
const ajv = new Ajv2020({ strict: true, coerceTypes: false, removeAdditional: false })
addFormats(ajv, { mode: 'full' })
ajv.addSchema(schema)
const validators = Object.fromEntries(Object.entries(schema.properties).map(([key, value]) => [key, ajv.compile({ $ref: `${schema.$id}${value.$ref}` })])) as Record<keyof Wire, ValidateFunction<unknown>>
const idPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u

export class ReadError extends Error {
  constructor(public readonly auth: boolean, message = 'Published data could not be loaded. Please retry.') { super(message); this.name = 'ReadError' }
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new ReadError(false, 'The API returned an invalid published-data response.')
  return value as Record<string, unknown>
}

export function decode<K extends keyof Wire>(kind: K, value: unknown, corpus?: string): Wire[K] {
  const envelope = object(value)
  if (Object.keys(envelope).sort().join(',') !== 'data,meta' || !validators[kind](envelope.data)) throw new ReadError(false, 'The API returned an invalid published-data response.')
  const meta = parseContract('ResponseMeta', envelope.meta)
  const data = envelope.data as Wire[K]
  const view: ViewInfo = kind === 'info' ? data as ViewInfo : (data as CompanyPage | FactPage | CompanyGraph | PublishedEvidence).view
  if (meta.versions.corpus_version_id !== view.corpus_version_id || (corpus !== undefined && corpus !== view.corpus_version_id)) throw new ReadError(false, 'The returned corpus version does not match this view.')
  if (kind === 'evidence') {
    const evidence = data as PublishedEvidence
    parseContract('TextEvidence', evidence.evidence.record)
    if (meta.versions.filing_version_id !== evidence.evidence.record.source.filing_version_id || meta.versions.parse_version_id !== evidence.evidence.record.source.parse_version_id) throw new ReadError(false, 'The returned source version does not match this view.')
  }
  return data
}

function canonical(value: string): string {
  if (!idPattern.test(value)) throw new ReadError(false, 'A valid published identifier is required.')
  return value
}

function query(options: ReadOptions): URLSearchParams {
  const values = new URLSearchParams({ corpus_version_id: canonical(options.corpus), historical: String(options.historical) })
  if (options.asOf) values.set('as_of_date', options.asOf)
  return values
}

function sourceQuery(options: ReadOptions): string {
  const values = new URLSearchParams({ historical: String(options.historical) })
  if (options.asOf) values.set('as_of_date', options.asOf)
  return values.toString()
}

export class PublishedApi {
  constructor(private readonly token: string, private readonly base = getApiBaseUrl()) {}

  private async request(path: string, signal: AbortSignal, body?: URLSearchParams | RetrievalRequest): Promise<Response> {
    try {
      const login = body instanceof URLSearchParams
      const response = await fetch(this.base + path, {
        method: body ? 'POST' : 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]),
        headers: login ? { 'Content-Type': 'application/x-www-form-urlencoded' } : { Authorization: `Bearer ${this.token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
        ...(body ? { body: login ? body : JSON.stringify(body) } : {}),
      })
      if (response.status === 401) throw new ReadError(!login, login ? 'Sign-in failed. Check your username and password.' : 'Your session has expired. Please sign in again.')
      if (!response.ok) throw new ReadError(false, response.status === 404 ? 'No matching resource is published in this view.' : undefined)
      return response
    } catch (error: unknown) {
      if (signal.aborted) throw new DOMException('Request cancelled.', 'AbortError')
      if (error instanceof ReadError) throw error
      throw new ReadError(false)
    }
  }

  static async login(username: string, password: string, signal: AbortSignal): Promise<PublishedApi> {
    const api = new PublishedApi('')
    const response = await api.request('/v1/auth/token', signal, new URLSearchParams({ grant_type: 'password', username, password }))
    const result = object(await response.json())
    if (typeof result.access_token !== 'string' || result.access_token.length < 1 || result.access_token.length > 8192 || result.token_type !== 'bearer') throw new ReadError(false)
    return new PublishedApi(result.access_token)
  }

  private async read<K extends keyof Wire>(path: string, kind: K, signal: AbortSignal, corpus?: string, options?: ReadOptions): Promise<Wire[K]> {
    const response = await this.request(path, signal)
    const result = decode(kind, await response.json() as unknown, corpus)
    if (options && kind !== 'info') {
      const view = (result as Exclude<Wire[keyof Wire], ViewInfo>).view
      if (view.historical !== options.historical || view.as_of_date !== (options.asOf || null)) throw new ReadError(false, 'The returned history or date view does not match the selection.')
    }
    return result
  }

  current(signal: AbortSignal): Promise<ViewInfo> { return this.read('/v1/published-corpus', 'info', signal) }
  async answer(options: ReadOptions, input: AnswerInput, signal: AbortSignal): Promise<AnswerResult> {
    canonical(options.corpus)
    if (input.company) canonical(input.company)
    const body = answerRequest(options, input)
    const response = await this.request('/v1/answers', signal, body)
    try { return parseAnswer(await response.json() as unknown, options, body) }
    catch { throw new ReadError(false, 'The answer or its exact source could not be verified.') }
  }
  companies(options: ReadOptions, text: string, offset: number, signal: AbortSignal): Promise<CompanyPage> {
    const values = query(options); values.set('q', text); values.set('offset', String(offset))
    return this.read(`/v1/companies?${values}`, 'companies', signal, options.corpus, options)
  }
  async facts(options: ReadOptions, company: string, offset: number, signal: AbortSignal): Promise<FactPage> {
    const values = query(options); values.set('offset', String(offset))
    const result = await this.read(`/v1/companies/${canonical(company)}/facts?${values}`, 'facts', signal, options.corpus, options)
    if (result.company.id !== company) throw new ReadError(false)
    return result
  }
  async graph(options: ReadOptions, company: string, signal: AbortSignal): Promise<CompanyGraph> {
    const result = await this.read(`/v1/companies/${canonical(company)}/graph?${query(options)}`, 'graph', signal, options.corpus, options)
    if (result.company.id !== company) throw new ReadError(false)
    return result
  }
  async evidence(options: ReadOptions, observation: string, evidence: string, signal: AbortSignal): Promise<PublishedEvidence> {
    const path = `/v1/corpora/${canonical(options.corpus)}/observations/${canonical(observation)}/evidence/${canonical(evidence)}?${sourceQuery(options)}`
    const result = await this.read(path, 'evidence', signal, options.corpus, options)
    if (result.observation_id !== observation || result.evidence.record.id !== evidence) throw new ReadError(false)
    return result
  }
  async pdf(options: ReadOptions, observation: string, sha256: string, signal: AbortSignal): Promise<Uint8Array<ArrayBuffer>> {
    const path = `/v1/corpora/${canonical(options.corpus)}/observations/${canonical(observation)}/source.pdf?${sourceQuery(options)}`
    const response = await this.request(path, signal)
    if (response.headers.get('x-corpus-version-id') !== options.corpus || response.headers.get('etag') !== `"${sha256}"` || response.headers.get('content-type')?.split(';')[0] !== 'application/pdf') throw new ReadError(false, 'The original source identity could not be verified.')
    const maximum = 64_000_000
    const length = Number(response.headers.get('content-length'))
    if (!Number.isSafeInteger(length) || length < 1 || length > maximum || !response.body) throw new ReadError(false, 'The source exceeds the viewer limit or is unavailable.')
    const reader = response.body.getReader()
    const chunks: Uint8Array[] = []
    let size = 0
    try {
      while (true) {
        if (signal.aborted) throw new DOMException('Request cancelled.', 'AbortError')
        const next = await reader.read()
        if (next.done) break
        size += next.value.length
        if (size > maximum || size > length) throw new ReadError(false, 'The source exceeds the viewer limit.')
        chunks.push(next.value)
      }
    } finally { await reader.cancel(); reader.releaseLock() }
    if (size !== length) throw new ReadError(false, 'The original source is incomplete.')
    const bytes = new Uint8Array(size)
    let offset = 0
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length }
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))
    const actual = Array.from(digest, (value) => value.toString(16).padStart(2, '0')).join('')
    if (actual !== sha256) throw new ReadError(false, 'The original source hash does not match. Rendering was stopped.')
    return bytes
  }
}
