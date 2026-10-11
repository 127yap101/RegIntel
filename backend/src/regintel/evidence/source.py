"""Read one bounded original-source handle and verify the bytes returned to callers."""

import hashlib
import os
import stat

from regintel.ingestion.models import SourceBlob
from regintel.ingestion.storage import SourceStorage, UploadError


def read_verified_source(storage: SourceStorage, blob: SourceBlob) -> bytes:
    """Return the exact hash-verified bytes, without reopening a mutable source path.

    The storage reader checks the content-addressed path and all ancestors for
    symlinks/junctions. Both handle metadata checks and a bounded extra-byte read
    detect size changes; the digest authenticates the actual returned snapshot.
    """
    if blob.storage_key != f"sha256/{blob.sha256}.pdf":
        raise UploadError(503, "SOURCE_STORAGE_UNAVAILABLE")
    if blob.byte_size > storage.settings.max_bytes:
        raise UploadError(400, "SOURCE_HASH_MISMATCH")
    with storage.read(blob) as stream:
        descriptor = stream.fileno()
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise UploadError(503, "SOURCE_STORAGE_UNAVAILABLE")
        if before.st_size != blob.byte_size:
            raise UploadError(400, "SOURCE_HASH_MISMATCH")
        chunks: list[bytes] = []
        observed = 0
        digest = hashlib.sha256()
        while chunk := stream.read(min(1024 * 1024, blob.byte_size - observed + 1)):
            observed += len(chunk)
            if observed > blob.byte_size:
                raise UploadError(400, "SOURCE_HASH_MISMATCH")
            chunks.append(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or after.st_size != blob.byte_size
            or observed != blob.byte_size
            or digest.hexdigest() != blob.sha256
        ):
            raise UploadError(400, "SOURCE_HASH_MISMATCH")
    return b"".join(chunks)
