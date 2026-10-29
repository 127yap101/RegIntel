import { parseContract } from '../contracts/runtime'
import type { PublishedNumericalObservation, PublishedObservation } from './generated'

export function checkNumericalObservation(observation: PublishedObservation | PublishedNumericalObservation): void {
  if (!('proof' in observation)) return
  if (observation.schema_version !== 'native-numerical-observation-1') throw new Error('Native numerical schema is unavailable')
  const proof = observation.proof
  if (proof.parse_version_id !== observation.parse_version_id || proof.filing_version_id !== observation.filing_version_id || observation.validation_run_id !== observation.native_acceptance_id || observation.review_id !== observation.native_acceptance_id) throw new Error('Native numerical source or acceptance differs')
  const words = new Map<string, (typeof proof.phrases)[number]['words'][number]['evidence']>()
  const sourceKey = (source: (typeof proof.cells)[number]['source']): string => [source.filing_id, source.filing_version_id, source.parse_version_id, source.page_id, source.page_index].join(':')
  for (const phrase of proof.phrases) {
    const first = phrase.words[0]
    if (!first) throw new Error('Native numerical phrase is empty')
    const cell = proof.cells.find((item) => item.role === phrase.role)
    if (cell && (sourceKey(cell.source) !== sourceKey(first.evidence.source) || cell.word_evidence_ids.length !== phrase.words.length || cell.word_evidence_ids.some((id, index) => id !== phrase.words[index]?.evidence.id))) throw new Error('Native numerical table-cell membership differs')
    for (const [index, word] of phrase.words.entries()) {
      const evidence = parseContract('TextEvidence', word.evidence)
      if (sourceKey(evidence.source) !== sourceKey(first.evidence.source) || word.reference.capture_id !== first.reference.capture_id || word.reference.word_index !== first.reference.word_index + index) throw new Error('Native numerical phrase changes page or word order')
      if (evidence.source.parse_version_id !== proof.parse_version_id || evidence.source.filing_version_id !== proof.filing_version_id || evidence.source.filing_id !== proof.filing_id || word.reference.start !== 0 || evidence.span.start !== 0 || word.reference.end !== evidence.span.end || word.reference.quote !== evidence.span.quote) throw new Error('Native numerical word differs from retained source')
      const previous = words.get(evidence.id)
      if (previous && JSON.stringify(previous) !== JSON.stringify(evidence)) throw new Error('Native evidence identity conflicts')
      words.set(evidence.id, evidence)
    }
  }
  const ids = [...words.keys()].sort()
  if (observation.supports.length !== ids.length || observation.quantity.evidence_ids.length !== ids.length || observation.context_supports.length) throw new Error('Native numerical proof is incomplete')
  for (const [index, id] of ids.entries()) {
    const evidence = words.get(id)
    const span = observation.supports[index]
    if (!evidence || !span || span.evidence_id !== id || span.start !== 0 || span.end !== evidence.span.end || span.quote !== evidence.span.quote || [...span.quote].length !== span.end || observation.quantity.evidence_ids[index] !== id) throw new Error('Native numerical support differs from its complete proof')
  }
  parseContract('QuantitativeValue', observation.quantity)
}
