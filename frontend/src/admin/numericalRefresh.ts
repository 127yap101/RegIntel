import { sameValue } from '../contracts/equality'
import { checkNumericalPacket } from './numerical'
import { numericalGateDigest } from './numericalApplicability'
import type * as T from './generated'

export async function numericalRefreshRequest(packet: T.NumericalReviewPacket): Promise<T.NumericalRefreshRequest> {
  checkNumericalPacket(packet)
  return { schema_version: 'numerical-refresh-request-1', gate_run_id: packet.gate.id, gate_input_sha256: packet.gate.input_sha256, gate_result_sha256: await numericalGateDigest(packet.gate) }
}

export async function checkNumericalRefresh(value: T.NumericalRefreshResult, previous: T.NumericalReviewPacket, request: T.NumericalRefreshRequest): Promise<void> {
  const fail = () => { throw new Error('Refreshed checks differ from the selected source or request') }
  if (!sameValue(request, await numericalRefreshRequest(previous)) || !sameValue(value.request, request)) fail()
  checkNumericalPacket(value.packet)
  const old = previous.binding; const next = value.packet.binding
  if (value.previous_context_record_id !== previous.gate.context_record_id || value.context_changed !== (old.context_record_id !== next.context_record_id) || value.gate_changed !== (previous.gate.id !== value.packet.gate.id) || value.context_changed && !value.gate_changed) fail()
  for (const key of ['filing_id', 'filing_version_id', 'source_blob_id', 'source_sha256', 'parse_version_id', 'phrases', 'cells'] as const) {
    if (!sameValue(old[key], next[key])) fail()
  }
  if (!sameValue(previous.gate.evidence_ids, value.packet.gate.evidence_ids)) fail()
  if (!value.gate_changed && !sameValue(previous.gate, value.packet.gate)) fail()
}
