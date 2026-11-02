import type * as T from './generated'
import { sameValue } from '../contracts/equality'
import { checkNumericalGate, checkNumericalReview } from './numerical'

export function checkNumericalQueue(page: T.NumericalGateQueuePage): void {
  const ids = page.items.map((item) => item.gate.id)
  if (!sameValue(ids, [...new Set(ids)].sort()) || page.items.length > page.limit || page.has_more && page.items.length !== page.limit) throw new Error('The numerical queue is incomplete or unordered.')
  for (const item of page.items) {
    checkNumericalGate(item.gate)
    if (!sameValue(item.gate.evidence_ids, [...new Set(item.gate.evidence_ids)].sort())) throw new Error('Queued evidence membership differs.')
    if (item.review) checkNumericalReview(item.review, item.gate)
    const review = item.review?.request.decision ?? 'UNREVIEWED'
    if (page.state_filter !== 'ALL' && item.gate.state !== page.state_filter || page.review_filter !== 'ALL' && review !== page.review_filter) throw new Error('Numerical queue filters differ from the returned records.')
  }
}

export function queuedPacketMismatch(item: T.NumericalGateQueueItem, packet: T.NumericalReviewPacket): 'SOURCE' | 'REVIEW' | null {
  if (!sameValue(packet.gate, item.gate) || packet.binding.filing_version_id !== item.filing_version_id) return 'SOURCE'
  if (item.review && !sameValue(packet.review, item.review)) return 'REVIEW'
  return null
}
