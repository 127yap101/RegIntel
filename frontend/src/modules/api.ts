import Ajv2020 from 'ajv/dist/2020'
import addFormats from 'ajv-formats'
import { getApiBaseUrl } from '../api/health'
import { parseContract } from '../contracts/runtime'
import type { UserIdentity } from '../contracts/generated'
import { PublishedApi } from '../published/api'
import type { DefinitionDraft, ModuleWire, OrderRequest, StoredDefinition } from './generated'
import schema from './schema.json'

export type { ModuleWire } from './generated'

const ajv = new Ajv2020({ strict: true, coerceTypes: false, removeAdditional: false })
addFormats(ajv, { mode: 'full' })
ajv.addSchema(schema)
const validators = Object.fromEntries(Object.entries(schema.properties).map(([name, value]) => [name, ajv.compile({ $ref: `${schema.$id}${value.$ref}` })]))

export class ModuleError extends Error {
  constructor(readonly status: number, message: string) { super(message); this.name = 'ModuleError' }
}

export function orderInput(value: unknown): OrderRequest {
  if (!validators.order_input?.(value)) throw new ModuleError(422, 'Select a published company and a positive whole-share quantity.')
  return value as OrderRequest
}

export function definitionInput(value: unknown): DefinitionDraft {
  if (!validators.definition_input?.(value)) throw new ModuleError(422, 'Check the definition, its sources and exact decimal example inputs.')
  return value as DefinitionDraft
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new ModuleError(0, 'The module returned an invalid response.')
  return value as Record<string, unknown>
}

function checkedDefinition(value: StoredDefinition): void {
  for (const source of value.draft.sources) {
    let url: URL
    try { url = new URL(source.url) } catch { throw new ModuleError(0, 'The learning source link is invalid.') }
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new ModuleError(0, 'The learning source link is invalid.')
  }
  if ((value.calculation !== null) !== (value.draft.example !== null && value.draft.example !== undefined) || (value.calculation !== null && (value.calculation.state !== 'AVAILABLE' || value.calculation.result === null))) throw new ModuleError(0, 'The reviewed example is unavailable.')
}

export function decode<K extends keyof ModuleWire>(kind: K, value: unknown): ModuleWire[K] {
  const result = object(value)
  if (Object.keys(result).sort().join(',') !== 'data,meta' || !validators[kind]?.(result.data)) throw new ModuleError(0, 'The module returned an invalid response.')
  const meta = parseContract('ResponseMeta', result.meta)
  const data = result.data as ModuleWire[K]
  if (kind === 'learning_status') {
    const status = data as ModuleWire['learning_status']
    if ((status.state === 'AVAILABLE') !== (status.glossary_version_id !== null)) throw new ModuleError(0, 'Learning availability has no matching published version.')
  }
  if (kind === 'definition') checkedDefinition(data as ModuleWire['definition'])
  if (kind === 'reviewed') checkedDefinition((data as ModuleWire['reviewed']).definition)
  if (kind === 'drafts') {
    const queue = data as ModuleWire['drafts']
    if (queue.items.length > queue.limit || queue.items.length > queue.total || meta.versions.glossary_version_id !== null) throw new ModuleError(0, 'The private draft queue is invalid.')
    for (const item of queue.items) {
      checkedDefinition(item.definition)
      const expected = item.review === null ? 'PENDING_REVIEW' : item.review.review.decision === 'APPROVE' ? 'APPROVED' : 'REJECTED'
      if (item.state !== expected || (item.review !== null && item.review.definition.id !== item.definition.id) || (queue.state !== 'ALL' && queue.state !== item.state)) throw new ModuleError(0, 'The draft queue differs from its recorded reviews.')
    }
  }
  if (kind === 'glossary' || kind === 'context') {
    const definitions = kind === 'glossary' ? (data as ModuleWire['glossary']).definitions : [(data as ModuleWire['context']).definition]
    const terms = new Set<string>()
    for (const item of definitions) {
      if (item.review.decision !== 'APPROVE' || terms.has(item.definition.draft.term.toLowerCase())) throw new ModuleError(0, 'The glossary contains an unapproved or conflicting definition.')
      terms.add(item.definition.draft.term.toLowerCase()); checkedDefinition(item.definition)
    }
  }
  if (kind === 'glossary' || kind === 'learning_status' || kind === 'context') {
    const selected = data as ModuleWire['glossary'] | ModuleWire['learning_status'] | ModuleWire['context']
    if (meta.versions.glossary_version_id !== selected.glossary_version_id) throw new ModuleError(0, 'The returned glossary version changed.')
  }
  if (kind === 'portfolio' || kind === 'order' || kind === 'ledger' || kind === 'analytics') {
    const selected = data as ModuleWire['portfolio'] | ModuleWire['order'] | ModuleWire['ledger'] | ModuleWire['analytics']
    if (meta.versions.portfolio_version_id !== selected.portfolio_version_id) throw new ModuleError(0, 'The returned portfolio version changed.')
  }
  if (kind === 'analytics') {
    const analytics = data as ModuleWire['analytics']
    if (meta.versions.corpus_version_id !== null || meta.versions.quote_version_id !== null) throw new ModuleError(0, 'Ledger analytics require explicit source-version membership.')
    if (analytics.state === 'AVAILABLE') {
      if (!analytics.summary || analytics.input_entry_ids.length !== analytics.committed_orders || new Set(analytics.input_entry_ids).size !== analytics.input_entry_ids.length || (analytics.input_entry_ids.at(-1) ?? analytics.account_id) !== analytics.portfolio_version_id || analytics.summary.executed_orders + analytics.summary.rejected_orders !== analytics.committed_orders) throw new ModuleError(0, 'The analytics ledger is incomplete or mixed.')
      for (const item of analytics.companies) if ((item.quantity === 0) !== (item.position_state === 'CLOSED') || (item.closed_position_result !== null) !== (item.position_state === 'CLOSED')) throw new ModuleError(0, 'An open position cannot have a closed-position result.')
    } else if (analytics.summary !== null || analytics.input_entry_ids.length || analytics.companies.length || analytics.corpus_version_ids.length || analytics.quote_version_ids.length) throw new ModuleError(0, 'Budget-limited analytics cannot contain partial totals.')
  }
  if (kind === 'order') {
    const order = data as ModuleWire['order']
    if (order.portfolio_version_id !== order.entry.id || meta.versions.corpus_version_id !== order.entry.request.corpus_version_id || meta.versions.quote_version_id !== (order.entry.quote?.quote_version_id ?? null)) throw new ModuleError(0, 'The order source or ledger version differs.')
  }
  if (kind === 'context') {
    const context = data as ModuleWire['context']
    if (context.generated !== false || context.view.historical || meta.versions.corpus_version_id !== context.view.corpus_version_id || context.evidence.some((item) => item.observation_id !== context.observation.id || item.view.corpus_version_id !== context.view.corpus_version_id)) throw new ModuleError(0, 'The learning context differs from its selected source.')
  }
  return data
}

export class ModuleApi {
  readonly published: PublishedApi
  private constructor(private readonly token: string, readonly user: UserIdentity, private readonly base = getApiBaseUrl()) { this.published = new PublishedApi(token, base) }

  static async login(username: string, password: string, signal: AbortSignal): Promise<ModuleApi> {
    const base = getApiBaseUrl()
    let response: Response
    try {
      response = await fetch(`${base}/v1/auth/token`, { method: 'POST', credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]), body: new URLSearchParams({ grant_type: 'password', username, password }), headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
    } catch { throw new ModuleError(0, 'The backend could not be reached.') }
    if (!response.ok) throw new ModuleError(response.status, 'Sign-in failed. Check your username and password.')
    const payload = object(await response.json())
    if (typeof payload.access_token !== 'string' || payload.access_token.length < 1 || payload.access_token.length > 8192 || payload.token_type !== 'bearer') throw new ModuleError(0, 'The sign-in response is invalid.')
    const identity = await fetch(`${base}/v1/auth/me`, { headers: { Authorization: `Bearer ${payload.access_token}` }, credentials: 'omit', redirect: 'error', cache: 'no-store', signal })
    if (!identity.ok) throw new ModuleError(identity.status, 'Your current account could not be verified.')
    const user = parseContract('UserEnvelope', await identity.json()).data
    return new ModuleApi(payload.access_token, user, base)
  }

  async read<K extends keyof ModuleWire>(kind: K, path: string, signal: AbortSignal, body?: object): Promise<ModuleWire[K]> {
    let response: Response
    try {
      response = await fetch(this.base + path, { method: body ? 'POST' : 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]), headers: { Authorization: `Bearer ${this.token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) })
    } catch { throw new ModuleError(0, 'The request could not be confirmed. Retry a virtual order with its original request key.') }
    if (!response.ok) {
      const message = response.status === 401 ? 'Your session expired. Sign in again.' : response.status === 403 ? 'Your account cannot perform this action.' : response.status === 404 ? 'The selected resource is unavailable.' : response.status === 409 ? 'The request conflicts with stored history. Refresh before trying a changed request.' : response.status === 422 ? 'Check the submitted values.' : 'This module is unavailable. Please retry.'
      throw new ModuleError(response.status, message)
    }
    return decode(kind, await response.json())
  }

  async order(request: OrderRequest, signal: AbortSignal): Promise<ModuleWire['order']> {
    const result = await this.read('order', '/v1/portfolio/orders', signal, request)
    const actual = result.entry.request
    if (actual.request_id !== request.request_id || actual.company_id !== request.company_id || actual.corpus_version_id !== request.corpus_version_id || actual.quantity !== request.quantity || actual.side !== request.side) throw new ModuleError(0, 'The recorded order differs from the submitted request.')
    return result
  }
}
