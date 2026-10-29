import { sameValue } from '../contracts/equality'
import { parseContract } from '../contracts/runtime'
import { checkedNumericalProof, checkNumericalObservation } from '../published/native'
import { NUMERICAL_GATE_CODES, VALIDATION_CHECK_CODES } from './generated'
import type * as T from './generated'

function requireMatch(condition: boolean): void {
  if (!condition) throw new Error('Numerical review membership or mandatory checks differ')
}

function exactChecks(checks: readonly T.ValidationCheck[], passed: boolean): void {
  requireMatch(sameValue(checks.map((check) => check.code), VALIDATION_CHECK_CODES) && (!passed || checks.every((check) => check.state === 'PASS')))
}

export function checkNumericalReview(review: T.ReviewedNumericalContext, gate: T.BoundNumericalGateRun): void {
  requireMatch(review.request.gate_run_id === gate.id && review.gate_input_sha256 === gate.input_sha256 && sameValue(review.request.evidence_ids, gate.evidence_ids) && Boolean(review.request.note.trim()) && !review.request.note.includes('\0'))
  if (review.request.decision === 'CONFIRM_CONTEXT') requireMatch(gate.state === 'READY_FOR_REVIEW')
}

export function checkNumericalPacket(packet: T.NumericalReviewPacket): void {
  const { gate, binding, review } = packet
  const words = checkedNumericalProof(binding)
  requireMatch(gate.evidence_binding_id === binding.id && gate.context_record_id === binding.context_record_id && gate.parse_version_id === binding.parse_version_id && gate.source_sha256 === binding.source_sha256 && sameValue(gate.evidence_ids, words.map((word) => word.id)))
  requireMatch(sameValue(gate.checks.map((check) => check.code), NUMERICAL_GATE_CODES))
  const expected = gate.checks.some((check) => check.state === 'FAIL') ? 'QUARANTINED' : gate.checks.some((check) => check.state === 'REVIEW') ? 'REVIEW_REQUIRED' : 'READY_FOR_REVIEW'
  requireMatch(gate.state === expected && (expected !== 'QUARANTINED' || gate.quantity_proposal === null) && (expected !== 'READY_FOR_REVIEW' || gate.quantity_proposal !== null))
  if (gate.quantity_proposal) parseContract('FinancialPeriod', gate.quantity_proposal.period)
  if (review) checkNumericalReview(review, gate)
}

export function checkNumericalPreparation(value: T.NumericalPublicationPreparation, packet?: T.NumericalReviewPacket): void {
  exactChecks(value.checks, false)
  const passed = value.checks.every((check) => check.state === 'PASS')
  requireMatch((value.state === 'READY_FOR_ADAPTER') === passed && (value.proposed_input !== null) === passed)
  if (packet) {
    requireMatch(value.gate_run_id === packet.gate.id && value.gate_input_sha256 === packet.gate.input_sha256)
    if (packet.review) requireMatch(value.gate_result_sha256 === packet.review.gate_result_sha256)
  }
  const proposed = value.proposed_input
  if (!proposed) return
  checkNumericalPacket({ gate: proposed.gate, binding: proposed.proof, review: proposed.context_review })
  requireMatch(proposed.gate_run_id === value.gate_run_id && proposed.gate_input_sha256 === value.gate_input_sha256 && proposed.gate_result_sha256 === value.gate_result_sha256 && proposed.configuration_sha256 === value.configuration_sha256 && proposed.gate_input_sha256 === proposed.gate.input_sha256 && proposed.context_review.gate_result_sha256 === proposed.gate_result_sha256)
  requireMatch(proposed.context_review.request.decision === 'CONFIRM_CONTEXT' && proposed.gate.state === 'READY_FOR_REVIEW' && sameValue(proposed.quantity, proposed.gate.quantity_proposal) && proposed.metric.id === proposed.policy.metric_id && proposed.metric.kind === 'numeric_fact' && proposed.policy.quantity_kind === 'MONEY' && proposed.policy.period_kind === 'DURATION')
  requireMatch(proposed.quantity.currency !== null && proposed.quantity.normalized_unit !== null && proposed.quantity.basis !== 'UNKNOWN' && proposed.quantity.period.kind === 'DURATION' && proposed.quantity.period.start_date !== null && proposed.quantity.period.end_date !== null)
  if (packet) requireMatch(sameValue(proposed.gate, packet.gate) && sameValue(proposed.proof, packet.binding) && sameValue(proposed.context_review, packet.review))
}

export function checkNumericalCandidate(value: T.StoredNumericalCandidate, packet?: T.NumericalReviewPacket): void {
  checkNumericalPreparation(value.preparation, packet)
  const prepared = value.preparation.proposed_input
  requireMatch(prepared !== null && value.preparation.state === 'READY_FOR_ADAPTER' && value.record.request.gate_run_id === value.preparation.gate_run_id && value.record.request.prepared_input_id === prepared.id)
}

export function checkNumericalAcceptance(value: T.StoredNumericalAcceptance, candidate?: T.StoredNumericalCandidate): void {
  checkNumericalCandidate(value.candidate)
  const { record } = value
  const accepted = record.request.decision === 'ACCEPT'
  requireMatch(record.request.candidate_id === value.candidate.record.id && sameValue(record.request.evidence_ids, value.candidate.preparation.proposed_input?.gate.evidence_ids) && record.candidate_preparation_sha256 === value.candidate.record.preparation_sha256 && record.state === (accepted ? 'ACCEPTED_UNPUBLISHED' : 'REJECTED') && record.mandatory_m1_validation_complete === accepted && Boolean(record.request.note.trim()) && !record.request.note.includes('\0'))
  if (accepted) { exactChecks(record.checks, true); requireMatch(sameValue(record.checks, value.candidate.preparation.checks)) }
  else requireMatch(record.checks.length === 0)
  if (candidate) requireMatch(sameValue(value.candidate, candidate))
}

export function checkNumericalSnapshot(value: T.NumericalAcceptanceSnapshot): void {
  checkNumericalAcceptance(value.accepted); checkNumericalObservation(value.observation)
  const source = value.accepted.candidate.preparation.proposed_input
  if (!source) throw new Error('Native build input is unavailable')
  const { observation, accepted } = value
  requireMatch(accepted.record.state === 'ACCEPTED_UNPUBLISHED' && observation.native_acceptance_id === accepted.record.id && observation.candidate_id === accepted.candidate.record.id && observation.candidate_run_id === source.gate_run_id && observation.validator_configuration_sha256 === accepted.record.configuration_sha256 && observation.validation_input_sha256 === source.gate_input_sha256 && observation.subject_entity_id === source.subject_entity_id && observation.metric_id === source.metric.id && sameValue(observation.proof, source.proof) && sameValue(value.fresh_preparation, accepted.candidate.preparation))
  const quantity = observation.quantity
  requireMatch(sameValue({ raw_value: quantity.raw_value, normalized_value: quantity.normalized_value, normalized_unit: quantity.normalized_unit, currency: quantity.currency, period: quantity.period, basis: quantity.basis }, source.quantity))
}
