"""Returned source snapshots remain hash-bound, bounded and path-confined."""

import hashlib
import os
from pathlib import Path
from typing import BinaryIO

import pytest
from pydantic import SecretStr

from regintel.evidence.source import read_verified_source
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.models import SourceBlob
from regintel.ingestion.storage import SourceStorage, UploadError


@pytest.fixture
def storage(tmp_path: Path) -> SourceStorage:
    return SourceStorage(
        IngestionSettings(
            source_root=tmp_path / "sources",
            broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0"),
        )
    )


def store(storage: SourceStorage, data: bytes) -> SourceBlob:
    sha = hashlib.sha256(data).hexdigest()
    blob = SourceBlob(
        id="00000000-0000-4000-8000-000000000001",
        sha256=sha,
        byte_size=len(data),
        storage_key=f"sha256/{sha}.pdf",
    )
    (storage.root / blob.storage_key).write_bytes(data)
    return blob


def test_exact_original_snapshot_uses_one_handle(
    storage: SourceStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"%PDF-1.7\n" + b"original source" * 100_000 + b"%%EOF"
    blob = store(storage, data)
    original = storage.read
    reads: list[str] = []

    def counted_read(source: SourceBlob) -> BinaryIO:
        reads.append(source.id)
        return original(source)

    monkeypatch.setattr(storage, "read", counted_read)
    assert read_verified_source(storage, blob) == data
    assert reads == [blob.id]


@pytest.mark.parametrize("tamper", ["size", "same-size", "missing"])
def test_size_hash_and_missing_source_fail(storage: SourceStorage, tamper: str) -> None:
    data = b"original immutable source"
    blob = store(storage, data)
    path = storage.root / blob.storage_key
    if tamper == "missing":
        path.unlink()
        with pytest.raises(OSError):
            read_verified_source(storage, blob)
    else:
        path.write_bytes(b"replacement" if tamper == "size" else b"x" * len(data))
        with pytest.raises(UploadError, match="SOURCE_HASH_MISMATCH"):
            read_verified_source(storage, blob)


def test_limit_rejected_before_open(
    storage: SourceStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    blob = store(storage, b"bytes")
    storage.settings = storage.settings.model_copy(update={"max_bytes": 4})

    def forbidden_read(source: SourceBlob) -> BinaryIO:
        raise AssertionError("oversized source must not open")

    monkeypatch.setattr(storage, "read", forbidden_read)
    with pytest.raises(UploadError, match="SOURCE_HASH_MISMATCH"):
        read_verified_source(storage, blob)


@pytest.mark.parametrize("key", ["../../outside.pdf", "D:/outside.pdf", "/outside.pdf"])
def test_unsafe_storage_key_is_rejected_even_with_bypassed_model_validation(
    storage: SourceStorage, key: str
) -> None:
    blob = store(storage, b"original source")
    invalid = blob.model_copy(update={"storage_key": key})
    with pytest.raises(UploadError, match="SOURCE_STORAGE_UNAVAILABLE"):
        read_verified_source(storage, invalid)


@pytest.mark.skipif(os.name != "posix", reason="Named FIFO boundary requires a POSIX filesystem.")
def test_nonregular_fifo_is_rejected_without_waiting_for_writer(storage: SourceStorage) -> None:
    blob = store(storage, b"original source")
    path = storage.root / blob.storage_key
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(UploadError, match="SOURCE_STORAGE_UNAVAILABLE"):
        read_verified_source(storage, blob)


@pytest.mark.parametrize("part", ["file", "parent", "root"])
def test_symlink_or_junction_guard_precedes_open(
    storage: SourceStorage, monkeypatch: pytest.MonkeyPatch, part: str
) -> None:
    blob = store(storage, b"original bytes")
    target = {
        "file": storage.root / blob.storage_key,
        "parent": storage.root / "sha256",
        "root": storage.root,
    }[part]
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == target or original(path))
    with pytest.raises(UploadError, match="SOURCE_STORAGE_UNAVAILABLE"):
        read_verified_source(storage, blob)


def test_same_handle_metadata_size_change_is_detected(
    storage: SourceStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    blob = store(storage, b"exact original source")
    original = os.fstat
    calls = 0

    def changed_size(descriptor: int) -> os.stat_result:
        nonlocal calls
        result = original(descriptor)
        calls += 1
        if calls == 3:  # SourceStorage.read, reader-before, then reader-after.
            values = list(result)
            values[6] = result.st_size + 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(os, "fstat", changed_size)
    with pytest.raises(UploadError, match="SOURCE_HASH_MISMATCH"):
        read_verified_source(storage, blob)
