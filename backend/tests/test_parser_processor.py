"""Worker conversion uses verified private snapshots and fixed failure contracts."""

from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from pypdf import PdfWriter

from backend.tests.evidence_fixtures import synthetic_artifact, synthetic_configuration
from regintel.ingestion import parser as worker_parser
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.jobs import ParserFailure
from regintel.ingestion.parser import ParserProcessor
from regintel.ingestion.storage import SourceStorage, UploadError


def prepared(tmp_path):
    selected = synthetic_configuration()
    settings = IngestionSettings(
        source_root=tmp_path / "sources",
        broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0"),
        parser_configuration=selected,
    )
    storage = SourceStorage(settings)
    pdf = tmp_path / "original.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(pdf)
    payload = pdf.read_bytes()
    stage = storage.stage()
    stage.write(payload)
    source = stage.finish()
    return selected, storage, source.blob, payload


def test_parser_uses_same_verified_snapshot_and_removes_it(tmp_path, monkeypatch):
    selected, storage, blob, payload = prepared(tmp_path)
    processor = ParserProcessor(storage, selected, tmp_path / "models")
    parse_id, filing_id, version_id = (str(uuid4()) for _ in range(3))
    artifact = synthetic_artifact(
        configuration=selected,
        parse_id=parse_id,
        filing_id=filing_id,
        filing_version_id=version_id,
        blob=blob,
    )
    snapshot_paths = []
    monkeypatch.setattr(worker_parser, "create_converter", lambda models: (object(), {}))
    monkeypatch.setattr(
        worker_parser, "validate_runtime_configuration", lambda *args, **kwargs: None
    )

    def captured(converter, source):
        assert source.read_bytes() == payload
        assert source != storage.root / blob.storage_key
        snapshot_paths.append(source)
        # Replacement of the original after verification cannot affect conversion.
        (storage.root / blob.storage_key).write_bytes(b"changed after verified read")
        return {"status": "success"}

    def build(capture, *, source, **kwargs):
        assert source == snapshot_paths[0]
        assert source.read_bytes() == payload
        assert kwargs["source_sha256"] == blob.sha256
        return artifact

    monkeypatch.setattr(worker_parser, "capture_conversion", captured)
    monkeypatch.setattr(worker_parser, "build_artifact", build)
    assert processor(blob, parse_id, filing_id, version_id) == artifact
    assert not snapshot_paths[0].exists()


@pytest.mark.parametrize(
    "stage,code",
    [
        ("configuration", "PARSER_CONFIGURATION_MISMATCH"),
        ("conversion", "PARSE_FAILED"),
        ("artifact", "ARTIFACT_INVALID"),
    ],
)
def test_sdk_failures_are_fixed_and_snapshot_is_removed(tmp_path, monkeypatch, stage, code):
    selected, storage, blob, _ = prepared(tmp_path)
    snapshots = []
    monkeypatch.setattr(worker_parser, "create_converter", lambda models: (object(), {}))
    monkeypatch.setattr(
        worker_parser, "validate_runtime_configuration", lambda *args, **kwargs: None
    )

    def bad_configuration(*args, **kwargs):
        raise RuntimeError("Untrusted filing/configuration diagnostic")

    def convert(converter, source):
        snapshots.append(source)
        if stage == "conversion":
            raise RuntimeError("Untrusted filing diagnostic")
        return {}

    def bad_artifact(*args, **kwargs):
        raise worker_parser.AdapterError("STRUCTURE_INVALID")

    if stage == "configuration":
        monkeypatch.setattr(worker_parser, "create_converter", bad_configuration)
    monkeypatch.setattr(worker_parser, "capture_conversion", convert)
    monkeypatch.setattr(worker_parser, "build_artifact", bad_artifact)
    with pytest.raises(ParserFailure) as error:
        ParserProcessor(storage, selected, tmp_path / "models")(
            blob, *(str(uuid4()) for _ in range(3))
        )
    assert str(error.value) == code
    assert all(not source.exists() for source in snapshots)


def test_tampered_source_fails_before_sdk_initialization(tmp_path, monkeypatch):
    selected, storage, blob, _ = prepared(tmp_path)
    target = storage.root / blob.storage_key
    target.write_bytes(target.read_bytes().replace(b"/Producer", b"/ProduceX"))

    def must_not_initialize(*args):
        pytest.fail("Tampered source must fail before model initialization")

    monkeypatch.setattr(worker_parser, "create_converter", must_not_initialize)
    with pytest.raises(UploadError, match="SOURCE_HASH_MISMATCH"):
        ParserProcessor(storage, selected, tmp_path / "models")(
            blob, *(str(uuid4()) for _ in range(3))
        )


def test_selected_ingestion_identity_excludes_paths_and_broker_secret(tmp_path):
    selected, storage, _, _ = prepared(tmp_path)
    assert storage.settings.configuration_sha256 == selected.processing_configuration_sha256
    changed = storage.settings.model_copy(update={"source_root": tmp_path / "elsewhere"})
    assert changed.configuration_sha256 == selected.processing_configuration_sha256
    with pytest.raises(ValidationError):
        IngestionSettings(
            source_root=tmp_path,
            broker_url=storage.settings.broker_url,
            parser_configuration=selected,
            max_pages=1,
        )
