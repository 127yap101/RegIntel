"""Explicit refresh selection; refreshed machine checks never carry human decisions."""

import hashlib
from typing import Literal

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.gate_models import BoundGateInput, StoredBoundNumericalGate


class NumericalRefreshRequest(ContractModel):
    schema_version: Literal["numerical-refresh-request-1"] = "numerical-refresh-request-1"
    gate_run_id: CanonicalId
    gate_input_sha256: Sha256Hash
    gate_result_sha256: Sha256Hash


def require_refresh_selection(
    request: NumericalRefreshRequest, gate: StoredBoundNumericalGate
) -> None:
    if (
        request.gate_run_id != gate.result.id
        or request.gate_input_sha256 != gate.result.input_sha256
        or request.gate_result_sha256 != hashlib.sha256(canonical_bytes(gate.result)).hexdigest()
    ):
        raise ValueError("Refresh must retain the selected immutable gate and both hashes.")


def require_refresh_membership(
    previous: StoredBoundNumericalGate, refreshed: StoredBoundNumericalGate
) -> None:
    """Only approval/configuration snapshots may change; source selections stay exact."""
    old, new = previous.source_input, refreshed.source_input
    if (
        type(new) is not BoundGateInput
        or old.context.source_input.draft != new.context.source_input.draft
        or old.context.source_input.pages != new.context.source_input.pages
        or old.binding.parse_version_id != new.binding.parse_version_id
        or old.binding.filing_id != new.binding.filing_id
        or old.binding.filing_version_id != new.binding.filing_version_id
        or old.binding.source_blob_id != new.binding.source_blob_id
        or old.binding.source_sha256 != new.binding.source_sha256
        or old.binding.phrases != new.binding.phrases
        or old.binding.cells != new.binding.cells
        or previous.result.evidence_ids != refreshed.result.evidence_ids
        or new.current_context != new.context.source_input
    ):
        raise ValueError("Refreshed gates must preserve the selected exact source and evidence.")


class RefreshedNumericalGate(ContractModel):
    request: NumericalRefreshRequest
    previous_context_record_id: CanonicalId
    gate: StoredBoundNumericalGate
