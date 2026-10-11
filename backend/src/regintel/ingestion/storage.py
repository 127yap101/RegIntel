"""Bounded streamed immutable original PDFs in confined content-addressed storage."""

import hashlib
import os
import stat
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from pypdf import PdfReader

from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.models import SourceBlob


class UploadError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


def _plain_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise UploadError(503, "SOURCE_STORAGE_UNAVAILABLE")
    if path.resolve() != path:
        raise UploadError(503, "SOURCE_STORAGE_UNAVAILABLE")


def inspect_pdf(stream: BinaryIO, size: int, settings: IngestionSettings) -> int:
    if size < 16:
        raise UploadError(400, "INVALID_PDF")
    stream.seek(0)
    if stream.read(5) != b"%PDF-":
        raise UploadError(400, "INVALID_PDF")
    stream.seek(max(0, size - 1024))
    if not stream.read().rstrip().endswith(b"%%EOF"):
        raise UploadError(400, "INVALID_PDF")
    stream.seek(0)
    try:
        # Source bytes remain untouched. Nonfatal PDF diagnostics are not API payloads.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = PdfReader(stream, strict=False)
            if reader.is_encrypted:
                raise UploadError(400, "ENCRYPTED_PDF")
            count = len(reader.pages)
            if count < 1 or count > settings.max_pages:
                raise UploadError(413, "PAGE_LIMIT")
            for page in reader.pages:
                _ = page.mediabox
    except UploadError:
        raise
    except Exception:
        raise UploadError(400, "INVALID_PDF") from None
    return count


@dataclass(frozen=True)
class StoredSource:
    blob: SourceBlob
    page_count: int


class SourceStorage:
    def __init__(self, settings: IngestionSettings, *, create: bool = True) -> None:
        self.settings = settings
        self.root = settings.source_root
        _plain_path(self.root)
        if create:
            for path in (self.root, self.root / "staging", self.root / "sha256"):
                _plain_path(path)
                path.mkdir(parents=True, exist_ok=True)
        for path in (self.root, self.root / "sha256"):
            _plain_path(path)
            if not path.is_dir():
                raise UploadError(503, "SOURCE_STORAGE_UNAVAILABLE")

    def stage(self) -> "StagedUpload":
        _plain_path(self.root / "staging")
        return StagedUpload(self)

    def read(self, blob: SourceBlob) -> BinaryIO:
        path = self.root / blob.storage_key
        _plain_path(path)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_BINARY", 0)
        )
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise UploadError(503, "SOURCE_STORAGE_UNAVAILABLE")
        return os.fdopen(descriptor, "rb")

    def verify(self, blob: SourceBlob) -> int:
        with self.read(blob) as stream:
            size = stream.seek(0, os.SEEK_END)
            if size != blob.byte_size or size > self.settings.max_bytes:
                raise UploadError(400, "SOURCE_HASH_MISMATCH")
            stream.seek(0)
            hasher = hashlib.sha256()
            observed = 0
            while chunk := stream.read(1024 * 1024):
                observed += len(chunk)
                if observed > blob.byte_size:
                    raise UploadError(400, "SOURCE_HASH_MISMATCH")
                hasher.update(chunk)
            digest = hasher.hexdigest()
            size = stream.seek(0, os.SEEK_END)
            if digest != blob.sha256 or size != blob.byte_size or observed != blob.byte_size:
                raise UploadError(400, "SOURCE_HASH_MISMATCH")
            return inspect_pdf(stream, size, self.settings)


class StagedUpload:
    def __init__(self, storage: SourceStorage) -> None:
        self.storage = storage
        self.path = storage.root / "staging" / f"{uuid4()}.part"
        self.stream = self.path.open("xb+")
        self.digest = hashlib.sha256()
        self.size = 0

    def write(self, chunk: bytes) -> None:
        self.size += len(chunk)
        if self.size > self.storage.settings.max_bytes:
            raise UploadError(413, "BYTE_LIMIT")
        self.stream.write(chunk)
        self.digest.update(chunk)

    def finish(self) -> StoredSource:
        self.stream.flush()
        os.fsync(self.stream.fileno())
        pages = inspect_pdf(self.stream, self.size, self.storage.settings)
        sha = self.digest.hexdigest()
        blob = SourceBlob(
            id=str(uuid4()), sha256=sha, byte_size=self.size, storage_key=f"sha256/{sha}.pdf"
        )
        final = self.storage.root / blob.storage_key
        _plain_path(final)
        self.stream.close()
        try:
            os.link(self.path, final)
        except FileExistsError:
            # Concurrent content publication may win, but never trust an existing filename.
            self.storage.verify(blob)
        self.close()
        return StoredSource(blob, pages)

    def close(self) -> None:
        self.stream.close()
        self.path.unlink(missing_ok=True)
