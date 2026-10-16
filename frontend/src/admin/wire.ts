import Ajv2020 from 'ajv/dist/2020'
import addFormats from 'ajv-formats'
import type { ValidateFunction } from 'ajv'
import { parseContract } from '../contracts/runtime'
import type * as T from './generated'
import schema from './schema.json'

export interface Wire {
  queue: T.QueuePage; review_page: T.ReviewPage; metrics: T.MetricPage
  filing_job: T.FilingJob; upload: T.UploadMetadata; processing_job: T.ProcessingJob
  processing_request: T.ProcessingRequest; dispatch: T.DispatchReceipt
  validation: T.ValidationData; validation_request: T.ValidationRequest
  review_request: T.ReviewDecision; review_receipt: T.ReviewReceipt
  manifest: T.CorpusManifest; publication_request: T.PublicationRequest; evidence: T.EvidenceData
}
const ajv = new Ajv2020({ strict: true, coerceTypes: false, removeAdditional: false })
addFormats(ajv, { mode: 'full' }); ajv.addSchema(schema)
const validators = Object.fromEntries(Object.entries(schema.properties).map(([key, value]) => [key, ajv.compile({ $ref: `${schema.$id}${value.$ref}` })])) as Record<keyof Wire, ValidateFunction<unknown>>

export function checked<K extends keyof Wire>(kind: K, value: unknown): Wire[K] {
  if (!validators[kind](value)) throw new Error('Administrator contract is invalid')
  return value as Wire[K]
}

export function decode<K extends keyof Wire>(kind: K, value: unknown): Wire[K] {
  if (typeof value !== 'object' || value === null || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'data,meta') throw new Error('Invalid administrator envelope')
  const envelope = value as Record<string, unknown>
  const meta = parseContract('ResponseMeta', envelope.meta)
  const data = checked(kind, envelope.data)
  if (kind === 'filing_job') {
    const job = data as T.FilingJob
    if (meta.versions.filing_version_id !== job.filing_version_id || meta.versions.parse_version_id !== job.parse_version_id) throw new Error('Filing job source differs')
  }
  if (kind === 'processing_job' && meta.versions.parse_version_id !== (data as T.ProcessingJob).request.parse_version_id) throw new Error('Processing parse differs')
  if (kind === 'validation' && meta.versions.parse_version_id !== (data as T.ValidationData).run.parse_version_id) throw new Error('Validation parse differs')
  if (kind === 'manifest') {
    const manifest = data as T.CorpusManifest
    const ids = manifest.observations.map((item) => item.id)
    if (new Set(ids).size !== ids.length || manifest.active_observation_ids.some((id) => !ids.includes(id)) || manifest.new_acceptances.some((item) => !manifest.observations.some((stored) => sameValue(stored, item.observation)))) throw new Error('Build scope differs')
    for (const item of manifest.observations) if (item.quantity) parseContract('QuantitativeValue', item.quantity)
  }
  if (kind === 'review_page') {
    const page = data as T.ReviewPage
    if (meta.versions.parse_version_id !== page.parse_version_id || new Set(page.items.map((item) => item.candidate.id)).size !== page.items.length) throw new Error('Mixed review source')
    for (const item of page.items) {
      const { candidate, draft, result, review } = item
      if (candidate.parse_version_id !== page.parse_version_id || candidate.id !== result.candidate_id || candidate.raw_text !== draft.raw_text || candidate.kind !== draft.kind || candidate.subject_entity_id !== draft.subject_entity_id || candidate.object_entity_id !== draft.object_entity_id || candidate.relation_type !== draft.relation_type || candidate.metric_id !== draft.metric_id || (review && candidate.id !== review.candidate_id) || result.checks.length !== 16 || new Set(result.checks.map((check) => check.code)).size !== 16) throw new Error('Review candidate identity differs')
      const failures = result.checks.some((check) => check.state === 'FAIL')
      const reviews = result.checks.filter((check) => check.state === 'REVIEW')
      const eligible = !failures && reviews.every((check) => check.code === 'EXTRACTIVE_REVIEW')
      if (result.reviewer_eligible !== eligible || result.state !== (failures ? 'QUARANTINED' : reviews.length ? 'REVIEW' : 'PASS') || (page.state_filter !== 'ALL' && result.state !== page.state_filter)) throw new Error('Review gates differ')
      for (const span of [...draft.supports, ...result.context_supports.map((witness) => witness.span)]) {
        if ([...span.quote].length !== span.end - span.start || !candidate.evidence_ids.includes(span.evidence_id) && draft.supports.includes(span)) throw new Error('Review support differs')
      }
      if (result.quantity) parseContract('QuantitativeValue', result.quantity)
    }
  }
  if (kind === 'evidence') {
    const evidence = data as T.EvidenceData
    parseContract('TextEvidence', evidence.record)
    if (meta.versions.parse_version_id !== evidence.record.source.parse_version_id || meta.versions.filing_version_id !== evidence.record.source.filing_version_id) throw new Error('Evidence source version differs')
  }
  return data
}

export function canonical(value: string): string {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u.test(value)) throw new Error('A canonical identifier is required')
  return value
}

export function sameValue(left: unknown, right: unknown): boolean {
  if (left === right) return true
  if (Array.isArray(left) && Array.isArray(right)) return left.length === right.length && left.every((value, index) => sameValue(value, right[index]))
  if (typeof left !== 'object' || left === null || Array.isArray(left) || typeof right !== 'object' || right === null || Array.isArray(right)) return false
  const a = left as Record<string, unknown>; const b = right as Record<string, unknown>
  const keys = Object.keys(a).sort()
  return keys.join(',') === Object.keys(b).sort().join(',') && keys.every((key) => sameValue(a[key], b[key]))
}

export class PendingWrites {
  private bodies = new Map<string, unknown>()
  body<K extends 'review_request' | 'processing_request' | 'publication_request'>(kind: K, payload: object, identity: 'id' | 'idempotency_key'): Wire[K] {
    const key = `${kind}:${JSON.stringify(payload)}`
    if (!this.bodies.has(key)) this.bodies.set(key, checked(kind, { ...payload, [identity]: crypto.randomUUID() }))
    return checked(kind, this.bodies.get(key))
  }
  clear(): void { this.bodies.clear() }
}
