"""Inspection history contracts; authored inputs do not establish financial truth or review."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.tests.test_numerical_context import authored
from regintel.entities.models import canonical_bytes
from regintel.numerical import context_records
from regintel.numerical.context_gate import inspect_context
from regintel.numerical.context_records import (
    NumericalContextRecord,
    context_record_id,
    storage_configuration_sha256,
)


def record(tmp_path: Path) -> NumericalContextRecord:
    case = authored(tmp_path)
    source = case.input
    result = inspect_context(source)
    page = source.pages[0]
    config = storage_configuration_sha256()
    return NumericalContextRecord(
        id=context_record_id(result.id, config),
        filing_version_id=source.draft.filing_version_id,
        source_blob_id=page.source_blob_id,
        source_sha256=page.capture.source_sha256,
        input_sha256=hashlib.sha256(canonical_bytes(source)).hexdigest(),
        inspection_sha256=hashlib.sha256(canonical_bytes(result)).hexdigest(),
        storage_configuration_sha256=config,
        submitted_by=uuid4(),
        auth_version=1,
        source_input=source,
        inspection=result,
    )


def test_record_retains_complete_exact_input_and_proposed_decimal_json(tmp_path: Path) -> None:
    retained = record(tmp_path)
    assert NumericalContextRecord.model_validate_json(retained.model_dump_json()) == retained
    data = json.loads(retained.model_dump_json())
    assert data["inspection"]["quantity"]["normalized_value"] == "2500.20"
    assert retained.source_input.pages[0].capture.words
    assert not retained.acceptance_eligible and not retained.mandatory_m1_validation_complete
    assert retained.inspection.review_required


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "filing_version_id",
        "source_blob_id",
        "source_sha256",
        "input_sha256",
        "inspection_sha256",
        "storage_configuration_sha256",
        "acceptance_eligible",
        "mandatory_m1_validation_complete",
        "auth_version",
        "reviewed_by",
    ],
)
def test_record_cannot_promote_or_rebind_history(tmp_path: Path, field: str) -> None:
    data = record(tmp_path).model_dump(mode="python")
    if field in {"id", "filing_version_id", "source_blob_id"}:
        data[field] = str(uuid4())
    elif field.endswith("sha256"):
        data[field] = "0" * 64
    else:
        data[field] = True
    with pytest.raises(ValidationError):
        NumericalContextRecord.model_validate(data)


def test_rehashing_changed_quantity_does_not_forge_current_inspection(tmp_path: Path) -> None:
    retained = record(tmp_path)
    assert retained.inspection.quantity is not None
    quantity = retained.inspection.quantity.model_copy(update={"raw_value": "999"})
    result = retained.inspection.model_copy(update={"quantity": quantity})
    data = retained.model_dump(mode="python")
    data.update(
        inspection=result, inspection_sha256=hashlib.sha256(canonical_bytes(result)).hexdigest()
    )
    with pytest.raises(ValidationError, match="retained exact inputs"):
        NumericalContextRecord.model_validate(data)


def test_different_runtime_keeps_historical_result_without_reinterpretation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retained = record(tmp_path)
    monkeypatch.setattr(context_records, "context_configuration_sha256", lambda: "0" * 64)

    def forbidden(_value):
        pytest.fail("Historical interpretation must not be rerun under different code.")

    monkeypatch.setattr(context_records, "inspect_context", forbidden)
    assert NumericalContextRecord.model_validate_json(retained.model_dump_json()) == retained


@pytest.mark.parametrize("limit", ["MAX_INPUT_BYTES", "MAX_INSPECTION_BYTES"])
def test_history_limits_fail_without_truncating_retained_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    retained = record(tmp_path)
    monkeypatch.setattr(context_records, limit, 10)
    with pytest.raises(ValidationError, match="storage budget"):
        NumericalContextRecord.model_validate_json(retained.model_dump_json())
