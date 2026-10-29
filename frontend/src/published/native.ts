import { parseContract } from '../contracts/runtime'
import { sameValue } from '../contracts/equality'
import type { NumericalEvidenceBinding, PublishedNumericalObservation, PublishedObservation, TextEvidence } from './generated'

/** Retain separate original words; never synthesize a combined source quotation. */
export function checkedNumericalProof(proof: NumericalEvidenceBinding): readonly TextEvidence[] {
  const words = new Map<string, TextEvidence>()
  const required = ['value', 'row_label', 'period_header', 'issuer_header', 'table_scope', 'unit_header']
  if (required.some((role, index) => proof.phrases[index]?.role !== role || proof.phrases[index]?.ordinal !== 0) || new Set(proof.phrases.map((phrase) => `${phrase.role}:${phrase.ordinal}`)).size !== proof.phrases.length || proof.phrases.reduce((count, phrase) => count + phrase.words.length, 0) > 1024) throw new Error('Native numerical phrase membership differs')
  if (proof.cells.length !== 3 || proof.cells.some((cell, index) => cell.role !== required[index]) || new Set(proof.cells.map((cell) => cell.artifact_table_id)).size !== 1) throw new Error('Native numerical table membership differs')
  for (const phrase of proof.phrases) {
    const first = phrase.words[0]
    if (!first) throw new Error('Native numerical phrase is empty')
    const cell = phrase.ordinal === 0 ? proof.cells.find((item) => item.role === phrase.role) : undefined
    if (cell && (!sameValue(cell.source, first.evidence.source) || cell.word_evidence_ids.length !== phrase.words.length || cell.word_evidence_ids.some((id, index) => id !== phrase.words[index]?.evidence.id))) throw new Error('Native numerical table-cell membership differs')
    for (const [index, word] of phrase.words.entries()) {
      const evidence = parseContract('TextEvidence', word.evidence)
      if (!sameValue(evidence.source, first.evidence.source) || word.reference.capture_id !== first.reference.capture_id || word.reference.word_index !== first.reference.word_index + index) throw new Error('Native numerical phrase changes page or word order')
      if (evidence.source.parse_version_id !== proof.parse_version_id || evidence.source.filing_version_id !== proof.filing_version_id || evidence.source.filing_id !== proof.filing_id || word.reference.start !== 0 || evidence.span.start !== 0 || word.reference.end !== evidence.span.end || word.reference.quote !== evidence.span.quote) throw new Error('Native numerical word differs from retained source')
      const previous = words.get(evidence.id)
      if ([...evidence.span.quote].length !== evidence.span.end || previous && !sameValue(previous, evidence)) throw new Error('Native evidence identity conflicts')
      words.set(evidence.id, evidence)
    }
  }
  return [...words.values()].sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0)
}

export function checkNumericalObservation(observation: PublishedObservation | PublishedNumericalObservation): void {
  if (!('proof' in observation)) return
  if (observation.schema_version !== 'native-numerical-observation-1') throw new Error('Native numerical schema is unavailable')
  const proof = observation.proof
  if (proof.parse_version_id !== observation.parse_version_id || proof.filing_version_id !== observation.filing_version_id || observation.validation_run_id !== observation.native_acceptance_id || observation.review_id !== observation.native_acceptance_id) throw new Error('Native numerical source or acceptance differs')
  const words = checkedNumericalProof(proof)
  const ids = words.map((word) => word.id)
  if (observation.supports.length !== ids.length || observation.quantity.evidence_ids.length !== ids.length || observation.context_supports.length) throw new Error('Native numerical proof is incomplete')
  for (const [index, id] of ids.entries()) {
    const evidence = words[index]
    const span = observation.supports[index]
    if (!evidence || !span || span.evidence_id !== id || span.start !== 0 || span.end !== evidence.span.end || span.quote !== evidence.span.quote || [...span.quote].length !== span.end || observation.quantity.evidence_ids[index] !== id) throw new Error('Native numerical support differs from its complete proof')
  }
  parseContract('QuantitativeValue', observation.quantity)
}
