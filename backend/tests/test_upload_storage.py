"""Real PDF byte boundaries, confinement and concurrent immutable publication."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from pypdf import PdfWriter

from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.jobs import UploadMetadata
from regintel.ingestion.storage import SourceStorage, UploadError


def pdf_bytes(*, pages: int = 1, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("synthetic password")
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
def settings(tmp_path: Path) -> IngestionSettings:
    return IngestionSettings(
        source_root=tmp_path / "sources",
        broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0"),
    )


def store(storage: SourceStorage, data: bytes):
    stage = storage.stage()
    try:
        for start in range(0, len(data), 31):
            stage.write(data[start : start + 31])
        return stage.finish()
    finally:
        stage.close()


def test_original_bytes_exact_key_hash_and_duplicate(settings: IngestionSettings) -> None:
    storage = SourceStorage(settings)
    data = pdf_bytes()
    first, duplicate = store(storage, data), store(storage, data)
    assert first.blob.sha256 == hashlib.sha256(data).hexdigest() == duplicate.blob.sha256
    assert first.page_count == 1 == storage.verify(first.blob)
    assert (settings.source_root / first.blob.storage_key).read_bytes() == data
    assert list((settings.source_root / "staging").iterdir()) == []
    assert len(list((settings.source_root / "sha256").iterdir())) == 1


def test_concurrent_publication_never_overwrites(settings: IngestionSettings) -> None:
    storage = SourceStorage(settings)
    data = pdf_bytes()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: store(storage, data), range(8)))
    assert len({result.blob.sha256 for result in results}) == 1
    assert len(list((settings.source_root / "sha256").iterdir())) == 1
    assert list((settings.source_root / "staging").iterdir()) == []


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"<html>error</html>",
        b"%PDF-1.7 broken %%EOF",
        pdf_bytes()[:-10],
        pdf_bytes(encrypted=True),
    ],
)
def test_bad_sources_leave_no_published_blob(settings: IngestionSettings, data: bytes) -> None:
    storage = SourceStorage(settings)
    with pytest.raises(UploadError) as error:
        store(storage, data)
    assert error.value.status == 400
    assert list((settings.source_root / "sha256").iterdir()) == []
    assert list((settings.source_root / "staging").iterdir()) == []


def test_actual_stream_bytes_and_page_count_limits(settings: IngestionSettings) -> None:
    storage = SourceStorage(settings.model_copy(update={"max_bytes": 1024, "max_pages": 1}))
    with pytest.raises(UploadError, match="BYTE_LIMIT"):
        store(storage, b"x" * 1025)
    with pytest.raises(UploadError, match="PAGE_LIMIT"):
        store(storage, pdf_bytes(pages=2))
    assert list((settings.source_root / "staging").iterdir()) == []


def test_hash_tampering_rejected_in_worker_and_duplicate(settings: IngestionSettings) -> None:
    storage = SourceStorage(settings)
    source = store(storage, pdf_bytes())
    (settings.source_root / source.blob.storage_key).write_bytes(pdf_bytes(pages=2))
    with pytest.raises(UploadError, match="SOURCE_HASH_MISMATCH"):
        storage.verify(source.blob)
    with pytest.raises(UploadError, match="SOURCE_HASH_MISMATCH"):
        store(storage, pdf_bytes())


def test_linked_storage_is_rejected_before_creation(
    settings: IngestionSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.is_junction
    monkeypatch.setattr(
        Path, "is_junction", lambda path: path == settings.source_root or original(path)
    )
    with pytest.raises(UploadError, match="SOURCE_STORAGE_UNAVAILABLE"):
        SourceStorage(settings)
    assert not settings.source_root.exists()


@pytest.mark.parametrize(
    "url",
    [
        "redis://:x@remote.example:6379/0",
        "redis://127.0.0.1:6379/0",
        "redis://:x@127.0.0.1:6379/1",
        "redis://:x@redis:6379/0?foo=x",
    ],
)
def test_only_explicit_existing_broker(settings: IngestionSettings, url: str) -> None:
    with pytest.raises(ValidationError):
        IngestionSettings(source_root=settings.source_root, broker_url=SecretStr(url))


def test_config_hash_has_no_paths_or_credentials(settings: IngestionSettings) -> None:
    changed = settings.model_copy(
        update={
            "source_root": settings.source_root / "elsewhere",
            "broker_url": SecretStr("redis://:other@redis:6379/0"),
        }
    )
    assert changed.configuration_sha256 == settings.configuration_sha256
    assert (
        settings.model_copy(update={"max_pages": 1}).configuration_sha256
        != settings.configuration_sha256
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"company_entity_id": "invented"},
        {"document_type": "PDF"},
        {"source_url": "https://secret:password@example.com/file.pdf"},
        {"published_on": "2026-02-30"},
        {"company_name_raw": "\x00"},
    ],
)
def test_upload_metadata_cannot_add_authority_or_bad_provenance(extra: dict[str, str]) -> None:
    value = {"company_name_raw": "Synthetic Company", "document_type": "RHP", **extra}
    with pytest.raises(ValidationError):
        UploadMetadata.model_validate(value)
