import { getApiBaseUrl } from '../api/health'
import { parseContract } from '../contracts/runtime'
import { canonical, checked, decode } from './wire'
import type { Wire } from './wire'
import type * as T from './generated'

export class AdminError extends Error {
  constructor(public readonly auth: boolean, message = 'The administrator request could not be completed. Refresh the stored state before retrying.') { super(message); this.name = 'AdminError' }
}

export class AdminApi {
  constructor(private readonly token: string, private readonly base = getApiBaseUrl()) {}

  private async request(path: string, signal: AbortSignal, body?: object | File, login = false): Promise<Response> {
    try {
      const response = await fetch(this.base + path, { method: body ? 'POST' : 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(120_000)]),
        headers: login ? { 'Content-Type': 'application/x-www-form-urlencoded' } : { Authorization: `Bearer ${this.token}`, ...(body ? { 'Content-Type': body instanceof File ? 'application/pdf' : 'application/json' } : {}) },
        ...(body ? { body: login || body instanceof File ? body as URLSearchParams | File : JSON.stringify(body) } : {}) })
      if (response.status === 401 || response.status === 403) throw new AdminError(!login, response.status === 403 ? 'Current administrator access is required. Please sign in with an administrator account.' : login ? 'Sign-in failed. Check your username and password.' : 'Your administrator session has expired. Please sign in again.')
      if (!response.ok) throw new AdminError(false, response.status === 409 ? 'This decision conflicts with stored history or the current corpus. Refresh before retrying; existing records were preserved.' : response.status === 422 ? 'The source or decision is invalid. Check its exact evidence and required context.' : response.status === 413 ? 'The PDF exceeds the upload limit.' : undefined)
      return response
    } catch (error: unknown) {
      if (signal.aborted) throw new DOMException('Request cancelled.', 'AbortError')
      if (error instanceof AdminError) throw error
      throw new AdminError(false)
    }
  }

  async read<K extends keyof Wire>(kind: K, path: string, signal: AbortSignal, body?: object): Promise<Wire[K]> {
    const response = await this.request(path, signal, body)
    try { return decode(kind, await response.json() as unknown) }
    catch { throw new AdminError(false, 'The administrator response or its source could not be verified.') }
  }

  static async login(username: string, password: string, signal: AbortSignal): Promise<AdminApi> {
    const api = new AdminApi('')
    const response = await api.request('/v1/auth/token', signal, new URLSearchParams({ grant_type: 'password', username, password }), true)
    const value: unknown = await response.json()
    if (typeof value !== 'object' || value === null || !('access_token' in value) || typeof value.access_token !== 'string' || !value.access_token || value.access_token.length > 8192 || !('token_type' in value) || value.token_type !== 'bearer') throw new AdminError(false)
    const client = new AdminApi(value.access_token)
    const identity = await client.request('/v1/auth/admin/me', signal)
    const envelope: unknown = await identity.json()
    if (typeof envelope !== 'object' || envelope === null || !('data' in envelope) || !('meta' in envelope)) throw new AdminError(false)
    parseContract('ResponseMeta', envelope.meta)
    if (parseContract('UserIdentity', envelope.data).role !== 'admin') throw new AdminError(true)
    return client
  }

  async queue(kind: T.QueueKind, offset: number, signal: AbortSignal): Promise<T.QueuePage> {
    const page = await this.read('queue', `/v1/admin/workspace/queues/${kind}?offset=${offset}&limit=20`, signal)
    if (page.kind !== kind || page.offset !== offset || page.limit !== 20) throw new AdminError(false)
    return page
  }
  async reviews(id: string, filter: T.ReviewFilter, offset: number, signal: AbortSignal): Promise<T.ReviewPage> {
    const page = await this.read('review_page', `/v1/admin/workspace/reviews/${canonical(id)}?state=${filter}&offset=${offset}&limit=20`, signal)
    if (page.run_id !== id || page.state_filter !== filter || page.offset !== offset || page.limit !== 20) throw new AdminError(false)
    return page
  }
  async filing(id: string, signal: AbortSignal): Promise<T.FilingJob> {
    const job = await this.read('filing_job', `/v1/filing-jobs/${canonical(id)}`, signal)
    if (job.id !== id) throw new AdminError(false)
    return job
  }
  async processing(id: string, signal: AbortSignal): Promise<T.ProcessingJob> {
    const job = await this.read('processing_job', `/v1/admin/processing/jobs/${canonical(id)}`, signal)
    if (job.id !== id) throw new AdminError(false)
    return job
  }
  async build(id: string, signal: AbortSignal, operation?: 'publish' | 'rebuild'): Promise<T.CorpusManifest> {
    const manifest = await this.read('manifest', `/v1/admin/publication/builds/${canonical(id)}${operation ? `/${operation}` : ''}`, signal, operation ? {} : undefined)
    if (manifest.id !== id) throw new AdminError(false)
    return manifest
  }
  async upload(file: File, metadata: unknown, signal: AbortSignal): Promise<T.FilingJob> {
    const values = checked('upload', metadata)
    if (!file.size || file.size > 64 * 1024 * 1024) throw new AdminError(false, 'Select a nonempty PDF no larger than 64 MiB.')
    const query = new URLSearchParams(Object.entries(values).flatMap(([key, value]) => value == null ? [] : [[key, String(value)]]))
    const response = await this.request(`/v1/filings?${query}`, signal, file)
    return decode('filing_job', await response.json() as unknown)
  }
  async source(span: T.SourceSpan, parse: string, signal: AbortSignal): Promise<{ evidence: T.EvidenceData; bytes: Uint8Array<ArrayBuffer> }> {
    const evidence = await this.read('evidence', `/v1/evidence/${canonical(span.evidence_id)}`, signal)
    const record = evidence.record
    if (record.id !== span.evidence_id || record.source.parse_version_id !== parse || span.start < record.span.start || span.end > record.span.end || [...record.span.quote].slice(span.start - record.span.start, span.end - record.span.start).join('') !== span.quote) throw new AdminError(false, 'The selected exact source span differs.')
    const response = await this.request(`/v1/filing-versions/${canonical(record.source.filing_version_id)}/source.pdf`, signal)
    const length = Number(response.headers.get('content-length'))
    if (response.headers.get('etag') !== `"${evidence.source_sha256}"` || response.headers.get('content-type')?.split(';')[0] !== 'application/pdf' || !Number.isSafeInteger(length) || length < 1 || length > 64_000_000 || !response.body) throw new AdminError(false, 'The original source identity or length differs.')
    const chunks: Uint8Array[] = []; let size = 0
    const reader = response.body.getReader()
    try { while (true) { if (signal.aborted) throw new DOMException('Cancelled', 'AbortError'); const next = await reader.read(); if (next.done) break; size += next.value.length; if (size > length) throw new AdminError(false); chunks.push(next.value) } }
    finally { await reader.cancel(); reader.releaseLock() }
    if (size !== length) throw new AdminError(false)
    const bytes = new Uint8Array(size); let offset = 0
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length }
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (value) => value.toString(16).padStart(2, '0')).join('')
    if (digest !== evidence.source_sha256) throw new AdminError(false, 'The original source hash differs; rendering was stopped.')
    return { evidence, bytes }
  }
}
