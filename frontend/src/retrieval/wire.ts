import Ajv2020 from 'ajv/dist/2020'
import addFormats from 'ajv-formats'
import { parseContract } from '../contracts/runtime'
import type { ReadOptions } from '../published/api'
import type { AnswerResult, RetrievalRequest } from './generated'
import schema from './schema.json'

export type { AnswerResult } from './generated'
export interface AnswerInput { question: string; arm: 'B0' | 'B1' | 'B2' | 'B3'; company?: string }
const ajv = new Ajv2020({ strict: true, coerceTypes: false, removeAdditional: false })
addFormats(ajv, { mode: 'full' })
ajv.addSchema(schema)
const validate = ajv.compile({ $ref: `${schema.$id}${schema.properties.answer.$ref}` })
const validateRequest = ajv.compile({ $ref: `${schema.$id}${schema.properties.request.$ref}` })

export function answerRequest(options: ReadOptions, input: AnswerInput): RetrievalRequest {
  const body = { question: input.question, arm: input.arm, corpus_version_id: options.corpus, historical: options.historical, as_of_date: options.asOf || null, filters: { company_id: input.company ?? null, period: null, basis: null }, top_k: 5, context_budget: 2048, graph_hops: 1, numeric: null }
  if (!validateRequest(body)) throw new Error('Invalid answer request')
  return body as RetrievalRequest
}

export function parseAnswer(value: unknown, options: ReadOptions, request: RetrievalRequest): AnswerResult {
  if (typeof value !== 'object' || value === null || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'data,meta') throw new Error('Invalid answer envelope')
  const envelope = value as Record<string, unknown>
  if (!validate(envelope.data)) throw new Error('Invalid answer contract')
  const meta = parseContract('ResponseMeta', envelope.meta)
  const result = envelope.data as AnswerResult
  const { view, trace, hits } = result.retrieval
  if (view.corpus_version_id !== options.corpus || meta.versions.corpus_version_id !== options.corpus || view.historical !== options.historical || view.as_of_date !== (options.asOf || null) || trace.arm !== request.arm || trace.context_budget !== request.context_budget || trace.top_k !== request.top_k || trace.filters.company_id !== request.filters?.company_id || trace.filters.period !== null || trace.filters.basis !== null || trace.graph_hops !== request.graph_hops || trace.context_tokens > trace.context_budget || trace.provider_calls !== 0) throw new Error('Answer view differs from the selected request')
  if (result.retrieval.state !== view.state || (view.state !== 'AVAILABLE' && (result.claims.length || hits.length))) throw new Error('Unavailable answer contains claims')
  const ids = new Set<string>()
  for (const hit of hits) {
    if (ids.has(hit.observation.id)) throw new Error('Repeated observation')
    ids.add(hit.observation.id)
    if (hit.observation.quantity !== null) parseContract('QuantitativeValue', hit.observation.quantity)
    for (const citation of hit.citations) {
      if (citation.observation_id !== hit.observation.id || citation.filing_version_id !== hit.observation.filing_version_id || citation.parse_version_id !== hit.observation.parse_version_id || [...citation.span.quote].length !== citation.span.end - citation.span.start) throw new Error('Mixed source identity')
      const spans = [...hit.observation.supports, ...hit.observation.context_supports.map((context) => context.span)]
      if (!spans.some((span) => span.evidence_id === citation.span.evidence_id && span.start === citation.span.start && span.end === citation.span.end && span.quote === citation.span.quote)) throw new Error('Citation is outside approved support')
    }
  }
  for (const claim of result.claims) {
    const hit = hits.find((item) => item.observation.id === claim.observation_id)
    if (result.state !== 'NUMERIC_VALUE' && (!hit || claim.text !== hit.observation.raw_text || JSON.stringify(claim.citations) !== JSON.stringify(hit.citations) || JSON.stringify(claim.quantity ?? null) !== JSON.stringify(hit.observation.quantity))) throw new Error('Claim differs from returned source')
    if (claim.quantity) parseContract('QuantitativeValue', claim.quantity)
    if (!claim.citations.length || claim.citations.some((citation) => citation.observation_id !== claim.observation_id || [...citation.span.quote].length !== citation.span.end - citation.span.start)) throw new Error('Claim citation differs')
  }
  if (!['EXTRACTIVE_EVIDENCE', 'NUMERIC_VALUE'].includes(result.state) && result.claims.length) throw new Error('Abstention contains claims')
  return result
}
