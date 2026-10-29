import Ajv2020 from 'ajv/dist/2020'
import addFormats from 'ajv-formats'
import { parseContract } from '../contracts/runtime'
import type { ReadOptions } from '../published/api'
import type { ComparisonRequest, ComparisonResult, QuotesResult } from './generated'
import schema from './schema.json'
import { checkNumericalObservation } from '../published/native'

export type { ComparisonRequest, ComparisonResult, QuotesResult } from './generated'
export interface ComparisonInput {
  companies: readonly string[]
  metrics: readonly string[]
  period: { kind: 'INSTANT' | 'DURATION'; start_date: string | null; end_date: string | null; instant_date: string | null; raw_label: null }
  basis: 'STANDALONE' | 'CONSOLIDATED'
}

const ajv = new Ajv2020({ strict: true, coerceTypes: false, removeAdditional: false })
addFormats(ajv, { mode: 'full' })
ajv.addSchema(schema)
const validators = Object.fromEntries(Object.entries(schema.properties).map(([key, value]) => [key, ajv.compile({ $ref: `${schema.$id}${value.$ref}` })]))

function envelope(value: unknown): { data: unknown; meta: ReturnType<typeof parseMeta> } {
  if (typeof value !== 'object' || value === null || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'data,meta') throw new Error('Invalid analysis envelope')
  const result = value as Record<string, unknown>
  return { data: result.data, meta: parseMeta(result.meta) }
}
function parseMeta(value: unknown) { return parseContract('ResponseMeta', value) }
function periodKey(value: ComparisonRequest['period']): string { return JSON.stringify([value.kind, value.start_date, value.end_date, value.instant_date]) }
function sameIds(left: readonly string[], right: readonly string[]): boolean { return left.length === right.length && left.every((id, index) => id === right[index]) }

export function comparisonRequest(options: ReadOptions, input: ComparisonInput): ComparisonRequest {
  const request = { corpus_version_id: options.corpus, company_ids: input.companies, metric_ids: input.metrics, period: input.period, basis: input.basis, as_of_date: options.asOf || null }
  if (options.historical || !validators.request?.(request) || new Set(input.companies).size !== input.companies.length || new Set(input.metrics).size !== input.metrics.length) throw new Error('Select distinct published companies and numeric metrics in an active view.')
  return request as ComparisonRequest
}

export function parseComparison(value: unknown, request: ComparisonRequest): ComparisonResult {
  const { data, meta } = envelope(value)
  if (!validators.comparison?.(data)) throw new Error('Invalid comparison contract')
  const result = data as ComparisonResult
  const selected = result.selection
  if (meta.versions.corpus_version_id !== request.corpus_version_id || result.view.corpus_version_id !== request.corpus_version_id || result.view.historical || result.view.as_of_date !== (request.as_of_date ?? null) || selected.corpus_version_id !== request.corpus_version_id || !sameIds(selected.company_ids, request.company_ids) || !sameIds(selected.metric_ids, request.metric_ids) || selected.basis !== request.basis || selected.as_of_date !== (request.as_of_date ?? null) || periodKey(selected.period) !== periodKey(request.period) || selected.period.raw_label !== request.period.raw_label || !sameIds(result.companies.map((item) => item.id), request.company_ids) || !sameIds(result.rows.map((row) => row.metric.id), request.metric_ids)) throw new Error('Comparison scope differs from the selected request')
  for (const row of result.rows) {
    if (row.metric.kind !== 'numeric_fact' || !sameIds(row.cells.map((cell) => cell.company_id), request.company_ids) || row.differences.length !== row.cells.length - 1) throw new Error('Comparison companies or metrics differ')
    for (const cell of row.cells) {
      if ((cell.state === 'AVAILABLE') !== (cell.normalized !== null) || (cell.state === 'AVAILABLE' && (cell.inputs.length !== 1 || result.view.state !== 'AVAILABLE'))) throw new Error('Unavailable cell contains a number')
      const ids = new Set<string>()
      for (const input of cell.inputs) {
        const observation = input.observation
        checkNumericalObservation(observation)
        if (ids.has(observation.id) || input.metric.id !== row.metric.id || observation.metric_id !== row.metric.id || observation.subject_entity_id !== cell.company_id || observation.kind !== 'numeric_fact' || !observation.quantity) throw new Error('Comparison input identity differs')
        ids.add(observation.id)
        parseContract('QuantitativeValue', observation.quantity)
        const spans = [...observation.supports, ...observation.context_supports.map((item) => item.span)]
        if (spans.some((span) => [...span.quote].length !== span.end - span.start) || observation.quantity.evidence_ids.some((id) => !spans.some((span) => span.evidence_id === id))) throw new Error('Comparison evidence differs')
        if (cell.state === 'AVAILABLE' && (periodKey(observation.quantity.period) !== periodKey(request.period) || observation.quantity.basis !== request.basis || observation.quantity.normalized_value === null || cell.normalized?.currency !== observation.quantity.currency)) throw new Error('Available input has incompatible context')
      }
    }
    for (const [index, pair] of row.differences.entries()) {
      const baseline = row.cells[0]
      const comparison = row.cells[index + 1]
      if (!baseline || !comparison || pair.baseline_company_id !== baseline.company_id || pair.company_id !== comparison.company_id || (pair.state === 'AVAILABLE') !== (pair.difference !== null) || (pair.percentage_state === 'AVAILABLE') !== (pair.percentage_difference !== null)) throw new Error('Invalid derived result')
      const differenceUnit = baseline.normalized?.unit === '%' ? 'percentage points' : baseline.normalized?.unit
      if (pair.state === 'AVAILABLE' && (baseline.state !== 'AVAILABLE' || comparison.state !== 'AVAILABLE' || !pair.unit || pair.unit !== differenceUnit || baseline.normalized?.unit !== comparison.normalized?.unit || pair.currency !== baseline.normalized?.currency || pair.currency !== comparison.normalized?.currency)) throw new Error('Derived result has unavailable or incompatible inputs')
      if (pair.state !== 'AVAILABLE' && pair.percentage_state !== 'UNAVAILABLE') throw new Error('Unavailable difference contains a percentage')
      if (pair.input_observation_ids.length && !sameIds(pair.input_observation_ids, [baseline, comparison].flatMap((cell) => cell.state === 'AVAILABLE' && cell.inputs[0] ? [cell.inputs[0].observation.id] : []))) throw new Error('Derived result has mixed input IDs')
      if (pair.state === 'AVAILABLE' && pair.input_observation_ids.length !== 2) throw new Error('Derived result lacks exact inputs')
    }
  }
  return result
}

export function parseQuotes(value: unknown): QuotesResult {
  const { data, meta } = envelope(value)
  if (!validators.quotes?.(data) || meta.versions.quote_version_id !== null) throw new Error('Invalid quote availability contract')
  return data as QuotesResult
}
