"""Anonymous acquisition and offline verification of the narrow pinned model set.

No downloader, Hugging Face account, cached credential or remote converter is used.
Weights and publisher cards/licenses are retained together, outside Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, BinaryIO, Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import Field

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import Sha256Hash

HERON_REVISION = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"
TABLE_REVISION = "fc0f2d45e2218ea24bce5045f58a389aed16dc23"
HERON_FOLDER = "docling-project--docling-layout-heron"
TABLE_FOLDER = "docling-project--docling-models/model_artifacts/tableformer/accurate"
RAPID_FOLDER = "RapidOcr"
MANIFEST_NAME = "regintel-model-manifest.json"


@dataclass(frozen=True)
class AssetSpec:
    path: str
    url: str
    revision: str
    license: str
    expected_size: int | None = None
    expected_sha256: str | None = None
    max_bytes: int = 1024 * 1024


def _hf(
    repo: str,
    revision: str,
    remote: str,
    local: str,
    license: str,
    size: int | None = None,
    sha256: str | None = None,
) -> AssetSpec:
    return AssetSpec(
        local,
        f"https://huggingface.co/{repo}/resolve/{revision}/{remote}",
        revision,
        license,
        size,
        sha256,
        size or 1024 * 1024,
    )


ASSETS = (
    _hf(
        "docling-project/docling-layout-heron",
        HERON_REVISION,
        "model.safetensors",
        f"{HERON_FOLDER}/model.safetensors",
        "Apache-2.0",
        171658996,
        "00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c",
    ),
    *(
        _hf(
            "docling-project/docling-layout-heron",
            HERON_REVISION,
            name,
            f"{HERON_FOLDER}/{name}",
            "Apache-2.0",
        )
        for name in ("config.json", "preprocessor_config.json", "README.md")
    ),
    _hf(
        "docling-project/docling-models",
        TABLE_REVISION,
        "model_artifacts/tableformer/accurate/tableformer_accurate.safetensors",
        f"{TABLE_FOLDER}/tableformer_accurate.safetensors",
        "CDLA-Permissive-2.0",
        212758388,
        "2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9",
    ),
    _hf(
        "docling-project/docling-models",
        TABLE_REVISION,
        "model_artifacts/tableformer/accurate/tm_config.json",
        f"{TABLE_FOLDER}/tm_config.json",
        "CDLA-Permissive-2.0",
    ),
    _hf(
        "docling-project/docling-models",
        TABLE_REVISION,
        "README.md",
        "licenses/tableformer-model-card.md",
        "CDLA-Permissive-2.0",
    ),
    AssetSpec(
        "licenses/cdla-permissive-2.0.html",
        "https://cdla.dev/permissive-2-0/",
        "CDLA-Permissive-2.0",
        "CDLA-Permissive-2.0",
    ),
    AssetSpec(
        "licenses/apache-2.0.txt",
        "https://www.apache.org/licenses/LICENSE-2.0.txt",
        "Apache-2.0",
        "Apache-2.0",
    ),
    AssetSpec(
        "licenses/rapidocr-apache-2.0.txt",
        "https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.9.2/LICENSE",
        "v3.9.2",
        "Apache-2.0",
    ),
    *(
        AssetSpec(
            f"{RAPID_FOLDER}/{Path(remote).name}",
            f"https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/{remote}",
            "v3.9.2",
            "Apache-2.0",
            size,
            sha256,
            size,
        )
        for remote, size, sha256 in (
            (
                "onnx/PP-OCRv6/det/PP-OCRv6_det_tiny.onnx",
                1829618,
                "f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5",
            ),
            (
                "onnx/PP-OCRv6/rec/PP-OCRv6_rec_tiny.onnx",
                4489813,
                "e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b",
            ),
            (
                "onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                585532,
                "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
            ),
            (
                "paddle/PP-OCRv6/rec/PP-OCRv6_rec_tiny/ppocrv6_tiny_dict.txt",
                27156,
                "c5cbe34ef40c29c4df07ed012bf96569cb69a2d2a01a07027e9f13cb832bd9cd",
            ),
            ("README.md", 1140, "3dc91bb3cb667df783178917d69b38bfabb8c935596f34243a1c9f0d36916b6e"),
        )
    ),
)


class ModelAsset(ContractModel):
    path: str
    url: str
    revision: str
    license: str
    byte_size: int = Field(gt=0)
    sha256: Sha256Hash


class ModelManifest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    assets: tuple[ModelAsset, ...]


def manifest_bytes(manifest: ModelManifest) -> bytes:
    return json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _safe_target(root: Path, relative: str) -> Path:
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError("An absolute model root without aliases is required")
    parts = relative.split("/")
    if any(part in ("", ".", "..") or ":" in part or "\\" in part for part in parts):
        raise ValueError("Model path escapes its explicitly supplied root")
    target = root.joinpath(*parts)
    for part in (target, *target.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("Model symlinks/junctions are forbidden")
    if not target.resolve().is_relative_to(root):
        raise ValueError("Model path escapes its explicitly supplied root")
    return target


def _ensure_directory(root: Path, relative: str | None = None) -> None:
    """Create only missing ancestors; normalize owned model directories to 0755."""
    target = root if relative is None else _safe_target(root, relative)
    _safe_target(root, MANIFEST_NAME)
    missing: list[Path] = []
    cursor = target
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if not cursor.is_dir():
        raise ValueError("Model directory is not a directory")
    for directory in reversed(missing):
        _safe_target(root, MANIFEST_NAME)
        directory.mkdir(mode=0o755, exist_ok=True)
        relative_directory = (
            directory.relative_to(root).as_posix()
            if directory.is_relative_to(root) and directory != root
            else MANIFEST_NAME
        )
        _safe_target(root, relative_directory)
        os.chmod(directory, 0o755)
    # Existing ancestors above the explicitly supplied root are never changed.
    for directory in (
        root,
        *[
            root.joinpath(*target.relative_to(root).parts[:index])
            for index in range(1, len(target.relative_to(root).parts) + 1)
        ],
    ):
        _safe_target(
            root, directory.relative_to(root).as_posix() if directory != root else MANIFEST_NAME
        )
        if not directory.is_dir():
            raise ValueError("Model directory is not a directory")
        os.chmod(directory, 0o755)


@contextmanager
def _read_file(root: Path, relative: str) -> Iterator[BinaryIO]:
    path = _safe_target(root, relative)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Model artifact must be a regular file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Model artifact must be a regular file")
        handle = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with handle:
        yield handle


def _digest(root: Path, relative: str, limit: int) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with _read_file(root, relative) as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError("Model file exceeds its acquisition bound")
            digest.update(chunk)
    if size == 0:
        raise ValueError("Empty model artifact")
    return size, digest.hexdigest()


def _validate_expected(spec: AssetSpec, actual: tuple[int, str]) -> None:
    if spec.expected_size is not None and actual[0] != spec.expected_size:
        raise ValueError(f"Publisher size mismatch: {spec.path}")
    if spec.expected_sha256 is not None and actual[1] != spec.expected_sha256:
        raise ValueError(f"Publisher hash mismatch: {spec.path}")


def _validate_modes(root: Path, relative: str) -> None:
    if os.name == "posix":
        _validate_posix_modes(root, relative)


class _MountMetadata(Protocol):
    f_flag: int


def _read_only_filesystem(path: Path) -> bool:
    """Require a kernel read-only mount flag, never infer it from mode/access bits."""
    try:
        # These POSIX-only stdlib members are absent from Windows type stubs.
        statvfs_member = getattr(os, "statvfs", None)
        read_only_flag = getattr(os, "ST_RDONLY", None)
        if (
            not callable(statvfs_member)
            or not isinstance(read_only_flag, int)
            or read_only_flag <= 0
        ):
            return False
        statvfs = cast(Callable[[Path], _MountMetadata], statvfs_member)
        return bool(statvfs(path).f_flag & read_only_flag)
    except (AttributeError, OSError):
        return False


def _validate_posix_modes(root: Path, relative: str) -> None:
    """Read-only Windows bind mounts can expose synthetic 0777 POSIX modes."""
    target = _safe_target(root, relative)
    directories: list[Path] = []
    for directory in target.parents:
        if not directory.is_relative_to(root):
            break
        directories.append(directory)
    if not os.access(target, os.R_OK):
        raise ValueError("Model files must be readable by the current worker")
    if any(not os.access(directory, os.R_OK | os.X_OK) for directory in directories):
        raise ValueError("Model directories must allow worker read and traversal")
    wrong_file_mode = stat.S_IMODE(target.stat().st_mode) != 0o644
    wrong_directory_modes = [
        directory for directory in directories if stat.S_IMODE(directory.stat().st_mode) != 0o755
    ]
    if not wrong_file_mode and not wrong_directory_modes:
        return
    # Docker Desktop may expose 0777 for a Windows-hosted bind even when the
    # mount is read-only. Every used path must be read-only too: a nested writable
    # mount cannot inherit approval merely from a read-only model root.
    if _read_only_filesystem(root) and all(
        _read_only_filesystem(path) for path in (target, *directories)
    ):
        return
    if wrong_file_mode:
        raise ValueError("Model files must have public read-only access outside their owner")
    if wrong_directory_modes:
        raise ValueError("Model directories must allow worker read and traversal")


def _check_https(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Only anonymous HTTPS model downloads are allowed")


class _HttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        _check_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _publish(
    root: Path,
    temporary_relative: str,
    destination: str,
    actual: tuple[int, str],
    limit: int,
    *,
    reuse_existing: bool = False,
) -> None:
    temporary = _safe_target(root, temporary_relative)
    target = _safe_target(root, destination)
    try:
        os.link(temporary, target)
    except FileExistsError:
        existing = _digest(root, destination, limit)
        if not reuse_existing and existing != actual:
            raise ValueError("Concurrent model acquisition differs") from None
    # A matching file published by another process must also be worker-readable.
    _safe_target(root, destination)
    os.chmod(target, 0o644)


def _atomic_bytes(root: Path, relative: str, data: bytes, *, reuse_existing: bool = False) -> None:
    target = _safe_target(root, relative)
    if reuse_existing and target.exists():
        # Receipts are not authoritative and must never overwrite prior acquisitions.
        _digest(root, relative, 4096)
        return
    temporary_relative = str(Path(relative).with_name(f".{target.name}.{uuid4().hex}.part"))
    # Manifest/receipt names are at the root; catalogue paths use portable '/' separators.
    temporary_relative = temporary_relative.replace("\\", "/")
    temporary = _safe_target(root, temporary_relative)
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        _publish(
            root,
            temporary_relative,
            relative,
            (len(data), hashlib.sha256(data).hexdigest()),
            max(len(data), 4096),
            reuse_existing=reuse_existing,
        )
    finally:
        _safe_target(root, temporary_relative).unlink(missing_ok=True)


def verify_models(root: Path) -> tuple[ModelManifest, str]:
    """Fail closed before conversion; no remote fallback or cache discovery."""
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("An existing absolute model directory is required")
    with _read_file(root, MANIFEST_NAME) as handle:
        data = handle.read(128 * 1024 + 1)
    _validate_modes(root, MANIFEST_NAME)
    if len(data) > 128 * 1024:
        raise ValueError("Oversized model manifest")
    manifest = ModelManifest.model_validate_json(data)
    if len(manifest.assets) != len(ASSETS):
        raise ValueError("Model asset set differs from the fixed catalogue")
    for spec, record in zip(ASSETS, manifest.assets, strict=True):
        if (record.path, record.url, record.revision, record.license) != (
            spec.path,
            spec.url,
            spec.revision,
            spec.license,
        ):
            raise ValueError("Model provenance differs from the fixed catalogue")
        actual = _digest(root, spec.path, spec.max_bytes)
        _validate_modes(root, spec.path)
        if actual != (record.byte_size, record.sha256):
            raise ValueError(f"Model integrity failure: {spec.path}")
        _validate_expected(spec, actual)
    return manifest, hashlib.sha256(manifest_bytes(manifest)).hexdigest()


def acquire_models(root: Path) -> tuple[ModelManifest, str]:
    """Fetch an explicit public allowlist and publish files exclusively."""
    if not root.is_absolute():
        raise ValueError("An absolute project-local destination is required")
    _safe_target(root, MANIFEST_NAME)
    _safe_target(root, "acquisition-receipt.json")
    _ensure_directory(root)
    if (root / MANIFEST_NAME).exists():
        return verify_models(root)
    records: list[ModelAsset] = []
    for spec in ASSETS:
        target = _safe_target(root, spec.path)
        parent = str(Path(spec.path).parent).replace("\\", "/")
        if parent != ".":
            _ensure_directory(root, parent)
        existing = _digest(root, spec.path, spec.max_bytes) if target.exists() else None
        if existing is not None:
            _validate_expected(spec, existing)
        # Unknown local files cannot establish their own baseline. Re-fetch small
        # un-hashed metadata/cards/licenses from the catalogue before trusting them.
        if existing is None or spec.expected_sha256 is None:
            temporary_relative = str(
                Path(spec.path).with_name(f".{target.name}.{uuid4().hex}.part")
            ).replace("\\", "/")
            temporary = _safe_target(root, temporary_relative)
            try:
                _check_https(spec.url)
                # Disable environment proxy credentials as well as account/cookie discovery.
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({}), _HttpsRedirect()
                )
                request = urllib.request.Request(
                    spec.url, headers={"User-Agent": "RegIntel-M1A-public-artifact-acquisition/1.0"}
                )
                size = 0
                with opener.open(request, timeout=90) as response, temporary.open("xb") as output:
                    _check_https(response.url)
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > spec.max_bytes:
                            raise ValueError("Model response exceeds its acquisition bound")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                actual = _digest(root, temporary_relative, spec.max_bytes)
                _validate_expected(spec, actual)
                os.chmod(temporary, 0o644)
                _publish(root, temporary_relative, spec.path, actual, spec.max_bytes)
            finally:
                _safe_target(root, temporary_relative).unlink(missing_ok=True)
        else:
            os.chmod(_safe_target(root, spec.path), 0o644)
        size, sha256 = _digest(root, spec.path, spec.max_bytes)
        _validate_expected(spec, (size, sha256))
        records.append(
            ModelAsset(
                path=spec.path,
                url=spec.url,
                revision=spec.revision,
                license=spec.license,
                byte_size=size,
                sha256=sha256,
            )
        )
        print(f"verified {spec.path}: {size} bytes", flush=True)
    manifest = ModelManifest(assets=tuple(records))
    _atomic_bytes(root, MANIFEST_NAME, manifest_bytes(manifest))
    _atomic_bytes(
        root,
        "acquisition-receipt.json",
        json.dumps(
            {"acquired_at": datetime.now(UTC).isoformat(), "anonymous_public_downloads": True}
        ).encode("utf-8"),
        reuse_existing=True,
    )
    return verify_models(root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--acquire", action="store_true")
    arguments = parser.parse_args()
    manifest, sha256 = (
        acquire_models(arguments.root) if arguments.acquire else verify_models(arguments.root)
    )
    print(
        json.dumps(
            {
                "model_manifest_sha256": sha256,
                "assets": len(manifest.assets),
                "total_bytes": sum(asset.byte_size for asset in manifest.assets),
            }
        )
    )


if __name__ == "__main__":
    main()
