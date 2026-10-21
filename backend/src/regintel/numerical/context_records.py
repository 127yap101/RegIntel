"""Immutable inspection history, distinct from M1 validation, review and acceptance."""

import hashlib
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.context_gate import context_configuration_sha256, inspect_context
from regintel.numerical.context_models import NumericalContextInput, NumericalContextInspection

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_INSPECTION_BYTES = 1024 * 1024


def context_record_id(inspection_id: str, storage_configuration_sha256: str) -> str:
    key = f"numerical-context-record:{inspection_id}:{storage_configuration_sha256}"
    return str(UUID(bytes=hashlib.sha256(key.encode("ascii")).digest()[:16], version=4))


def storage_configuration_sha256() -> str:
    package = Path(__file__).resolve().parents[1]
    sources = (
        ("numerical/context_records.py", package / "numerical/context_records.py"),
        ("numerical/context_inputs.py", package / "numerical/context_inputs.py"),
        ("numerical/context_storage.py", package / "numerical/context_storage.py"),
        (
            "infra/migrations/0013_numerical_context.sql",
            Path(__file__).resolve().parents[4] / "infra/migrations/0013_numerical_context.sql",
        ),
    )
    digest = hashlib.sha256()
    for name, path in sources:
        body = path.read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


class NumericalContextRecord(ContractModel):
    schema_version: Literal["stored-numerical-context-1"] = "stored-numerical-context-1"
    scope: Literal["PREPARATION_INSPECTION_ONLY"] = "PREPARATION_INSPECTION_ONLY"
    id: CanonicalId
    filing_version_id: CanonicalId
    source_blob_id: CanonicalId
    source_sha256: Sha256Hash
    input_sha256: Sha256Hash
    inspection_sha256: Sha256Hash
    storage_configuration_sha256: Sha256Hash
    submitted_by: UUID
    auth_version: Annotated[int, Field(strict=True, ge=1)]
    source_input: NumericalContextInput
    inspection: NumericalContextInspection
    acceptance_eligible: Literal[False] = False
    mandatory_m1_validation_complete: Literal[False] = False

    @model_validator(mode="after")
    def retained_identity(self) -> Self:
        source, result = self.source_input, self.inspection
        body, inspected = canonical_bytes(source), canonical_bytes(result)
        if not 0 < len(body) <= MAX_INPUT_BYTES or not 0 < len(inspected) <= MAX_INSPECTION_BYTES:
            raise ValueError("Context history exceeds its explicit storage budget.")
        if (
            hashlib.sha256(body).hexdigest() != self.input_sha256
            or hashlib.sha256(inspected).hexdigest() != self.inspection_sha256
            or result.source_input_sha256 != self.input_sha256
            or result.draft != source.draft
            or self.filing_version_id != source.draft.filing_version_id
            or tuple(page.id for page in source.pages) != source.draft.capture_ids
        ):
            raise ValueError("Context history must retain the exact inspected source and draft.")
        draft_sha = hashlib.sha256(canonical_bytes(source.draft)).hexdigest()
        result_key = f"{draft_sha}:{self.input_sha256}:{result.configuration_sha256}"
        expected = str(
            UUID(bytes=hashlib.sha256(result_key.encode("ascii")).digest()[:16], version=4)
        )
        if result.draft_sha256 != draft_sha or result.id != expected:
            raise ValueError("Inspection identity must bind its draft, input and configuration.")
        if self.id != context_record_id(result.id, self.storage_configuration_sha256):
            raise ValueError("Context history identity must bind the inspection and storage rules.")
        for page in source.pages:
            if page.filing_version_id == self.filing_version_id and (
                page.source_blob_id != self.source_blob_id
                or page.capture.source_sha256 != self.source_sha256
            ):
                raise ValueError("Context history differs from its uploaded primary source.")
        if result.configuration_sha256 == context_configuration_sha256():
            if inspect_context(source) != result:
                raise ValueError("Context inspection differs from its retained exact inputs.")
        return self
