import { sameValue } from '../contracts/equality'
import type * as T from './generated'

type Selection = T.NumericalApplicabilityRequirements | T.NumericalApplicabilityRequest
const kinds = ['CROSS_PAGE', 'BASIS', 'QUALIFIED_DEFAULT'] as const

function requireMatch(condition: boolean): void {
  if (!condition) throw new Error('Numerical applicability source membership differs')
}

// These audit payloads contain decimal strings and safe integers, never float geometry.
function canonicalJson(value: unknown): string {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value)
  if (typeof value === 'number' && Number.isSafeInteger(value)) return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (typeof value === 'object') return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(',')}}`
  throw new Error('Unsupported numerical audit value')
}

async function digest(value: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))
}
function hex(bytes: Uint8Array): string { return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('') }

export function applicabilitySelection(value: Selection) {
  return { gate_run_id: value.gate_run_id, gate_input_sha256: value.gate_input_sha256, gate_result_sha256: value.gate_result_sha256, binding_id: value.binding_id, value_cell_id: value.value_cell_id, row_cell_id: value.row_cell_id, period_cell_id: value.period_cell_id, assertions: value.assertions, reviewed_page_indices: value.reviewed_page_indices }
}

export async function checkApplicabilitySelection(value: Selection, packet: T.NumericalReviewPacket): Promise<void> {
  const { binding, gate } = packet
  requireMatch(value.gate_run_id === gate.id && value.gate_input_sha256 === gate.input_sha256 && value.binding_id === binding.id)
  requireMatch(value.gate_result_sha256 === hex(await digest(canonicalJson(gate))))
  requireMatch(value.value_cell_id === binding.cells[0]?.artifact_cell_id && value.row_cell_id === binding.cells[1]?.artifact_cell_id && value.period_cell_id === binding.cells[2]?.artifact_cell_id)
  const pages = [...new Set(binding.phrases.flatMap((phrase) => phrase.words.map((word) => word.evidence.source.page_index)))].sort((a, b) => a - b)
  requireMatch(sameValue(value.reviewed_page_indices, pages))
  let previous = -1
  for (const assertion of value.assertions) {
    const index = binding.phrases.findIndex((phrase) => phrase.role === assertion.role && phrase.ordinal === assertion.ordinal)
    const phrase = binding.phrases[index]
    const position = index * kinds.length + kinds.indexOf(assertion.kind)
    requireMatch(phrase !== undefined && sameValue(assertion.evidence_ids, phrase.words.map((word) => word.evidence.id)) && position > previous)
    previous = position
    if (assertion.kind === 'CROSS_PAGE') requireMatch(phrase?.words[0]?.evidence.source.page_index !== binding.cells[0]?.source.page_index)
    if (assertion.kind === 'BASIS') requireMatch(assertion.role === 'basis_context')
    if (assertion.kind === 'QUALIFIED_DEFAULT') requireMatch(assertion.role === 'unit_header' || assertion.role === 'basis_context')
  }
}

export async function checkApplicabilityRequirements(value: T.NumericalApplicabilityRequirements, packet: T.NumericalReviewPacket): Promise<void> {
  await checkApplicabilitySelection(value, packet)
  requireMatch(value.eligible === (value.blockers.length === 0 && value.assertions.length > 0))
  if (value.eligible) {
    const quantity = packet.gate.quantity_proposal
    requireMatch(packet.gate.state === 'REVIEW_REQUIRED' && packet.gate.checks.every((check) => check.state === 'PASS' || check.state === 'REVIEW' && ['CONTEXT_SCOPE', 'BASIS', 'SOURCE_LANGUAGE'].includes(check.code)))
    requireMatch(Boolean(quantity && quantity.basis !== 'UNKNOWN' && quantity.currency && quantity.normalized_unit && quantity.period.kind === 'DURATION' && quantity.period.start_date && quantity.period.end_date))
  }
}

export async function checkApplicabilityReview(value: T.ReviewedNumericalApplicability, packet: T.NumericalReviewPacket): Promise<void> {
  await checkApplicabilitySelection(value.request, packet)
  requireMatch(Boolean(value.request.note.trim()) && !value.request.note.includes('\0'))
  const bytes = (await digest(`numerical-applicability-review:${canonicalJson(value.request)}${value.configuration_sha256}`)).slice(0, 16)
  bytes[6] = (bytes[6]! & 15) | 64; bytes[8] = (bytes[8]! & 63) | 128
  const id = hex(bytes)
  requireMatch(value.id === `${id.slice(0, 8)}-${id.slice(8, 12)}-${id.slice(12, 16)}-${id.slice(16, 20)}-${id.slice(20)}`)
}

export function applicabilityInspectionPhrases(packet: T.NumericalReviewPacket, requirements: T.NumericalApplicabilityRequirements): readonly T.BoundNumericalPhrase[] {
  return packet.binding.phrases.filter((phrase) => packet.binding.cells.some((cell) => cell.role === phrase.role && phrase.ordinal === 0) || requirements.assertions.some((assertion) => assertion.role === phrase.role && assertion.ordinal === phrase.ordinal))
}

export function applicabilityInspected(packet: T.NumericalReviewPacket, requirements: T.NumericalApplicabilityRequirements, inspected: readonly string[]): boolean {
  const phrases = applicabilityInspectionPhrases(packet, requirements)
  return phrases.every((phrase) => phrase.words.some((word) => inspected.includes(word.evidence.id))) && requirements.reviewed_page_indices.every((page) => packet.binding.phrases.some((phrase) => phrase.words.some((word) => word.evidence.source.page_index === page && inspected.includes(word.evidence.id))))
}
