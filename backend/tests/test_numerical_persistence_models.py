"""Authored exact-reference and immutable-record contracts, without acceptance."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.tests.test_numerical_source_pages import fixture, prepare
from regintel.numerical.models import NumericalWordRef, StoredNumericalPage, page_capture_id
from regintel.numerical.source_pages import capture_bytes


@pytest.mark.parametrize("change", ["id", "source", "fingerprint"])
def test_stored_preparation_cannot_change_its_content_identity(tmp_path: Path, change: str) -> None:
    source, raw, source_sha, config_sha = fixture(tmp_path)
    capture = prepare(source, raw, source_sha, config_sha)
    filing, blob = str(uuid4()), str(uuid4())
    digest = hashlib.sha256(capture_bytes(capture)).hexdigest()
    value = {
        "id": page_capture_id(filing, blob, digest),
        "filing_version_id": filing,
        "source_blob_id": blob,
        "prepared_sha256": digest,
        "submitted_by": uuid4(),
        "auth_version": 1,
        "capture": capture,
    }
    valid = StoredNumericalPage.model_validate(value)
    assert StoredNumericalPage.model_validate_json(valid.model_dump_json()) == valid
    value[{"id": "id", "source": "source_blob_id", "fingerprint": "prepared_sha256"}[change]] = (
        "0" * 64 if change == "fingerprint" else str(uuid4())
    )
    with pytest.raises(ValidationError):
        StoredNumericalPage.model_validate(value)


@pytest.mark.parametrize("change", ["utf16", "reverse", "fraction", "bool", "index"])
def test_word_reference_requires_exact_bounded_unicode_offsets(change: str) -> None:
    value = {
        "capture_id": str(uuid4()),
        "word_index": 0,
        "start": 0,
        "end": 4,
        "quote": "😀e\u0301x",
    }
    assert NumericalWordRef.model_validate(value).quote == "😀e\u0301x"
    if change == "utf16":
        value["end"] = 5
    elif change == "reverse":
        value["start"] = 4
    elif change == "fraction":
        value["start"] = 0.5
    elif change == "bool":
        value["word_index"] = True
    else:
        value["word_index"] = 20_000
    with pytest.raises(ValidationError):
        NumericalWordRef.model_validate(value)
