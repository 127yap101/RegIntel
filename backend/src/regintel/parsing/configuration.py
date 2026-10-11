"""Lightweight, explicitly selected parser processing identity.

An application-owned descriptor records the configuration selected by the team.
Matching untrusted SDK data to that descriptor proves consistency, not approval.
Nothing here discovers configuration, reads credentials, imports the optional
parser SDK, accepts evidence, or writes authoritative state.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import Sha256Hash
from regintel.parsing.models import PackageVersion, ParseProvenance, package_manifest_sha256

MAX_DESCRIPTOR_BYTES = 64 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_PAGES = 2_000
MAX_CODE_BYTES = 2 * 1024 * 1024

SelectedCoordinateFrame = Literal[
    "RAW_PDF_BOTTOM_LEFT",
    "MEDIA_RELATIVE_BOTTOM_LEFT",
    "CROP_ROTATED_BOTTOM_LEFT",
    "CROP_ROTATED_TOP_LEFT",
]
ConfigurationErrorCode = Literal[
    "CONFIGURATION_FILE_INVALID",
    "CONFIGURATION_INVALID",
    "SDK_CONFIGURATION_INVALID",
    "RUNTIME_CONFIGURATION_MISMATCH",
    "ARTIFACT_PROVENANCE_MISMATCH",
]


class RuntimeConfigurationError(ValueError):
    """Fixed codes avoid exposing configuration content, paths or credentials."""

    def __init__(self, code: ConfigurationErrorCode) -> None:
        self.code = code
        super().__init__(code)


class SourceLimits(ContractModel):
    max_file_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_SOURCE_BYTES)] = MAX_SOURCE_BYTES
    max_pages: Annotated[int, Field(strict=True, ge=1, le=MAX_SOURCE_PAGES)] = MAX_SOURCE_PAGES


DEFAULT_SOURCE_LIMITS = SourceLimits()


class RuntimeCodeHashes(ContractModel):
    adapter_code_sha256: Sha256Hash
    geometry_code_sha256: Sha256Hash
    sdk_code_sha256: Sha256Hash
    artifact_models_code_sha256: Sha256Hash


class ParserRuntimeConfiguration(RuntimeCodeHashes):
    schema_version: Literal["1.0.0"] = "1.0.0"
    adapter_name: Literal["regintel-docling"] = "regintel-docling"
    adapter_version: Literal["1.0.0"] = "1.0.0"
    coordinate_frame: SelectedCoordinateFrame
    source_limits: SourceLimits = DEFAULT_SOURCE_LIMITS
    sdk_configuration_sha256: Sha256Hash
    model_manifest_sha256: Sha256Hash
    package_manifest_sha256: Sha256Hash
    backend_code_sha256: Sha256Hash

    @property
    def processing_configuration_sha256(self) -> str:
        """Bind every descriptor field, including frame, limits and application code."""
        return hashlib.sha256(canonical_configuration_bytes(self)).hexdigest()


def _canonical_bytes(value: object, code: ConfigurationErrorCode) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise RuntimeConfigurationError(code) from None


def _validated_descriptor(value: ParserRuntimeConfiguration) -> ParserRuntimeConfiguration:
    try:
        # Revalidate model_construct/model_copy callers as well as normal instances.
        return ParserRuntimeConfiguration.model_validate(value.model_dump(mode="python"))
    except (AttributeError, ValidationError):
        raise RuntimeConfigurationError("CONFIGURATION_INVALID") from None


def canonical_configuration_bytes(configuration: ParserRuntimeConfiguration) -> bytes:
    """Return stable UTF-8 JSON with no paths, timestamps or secret fields."""
    configuration = _validated_descriptor(configuration)
    return _canonical_bytes(configuration.model_dump(mode="json"), "CONFIGURATION_INVALID")


def _guard_file(path: Path) -> os.stat_result:
    """Inspect every existing ancestor without resolving away links or junctions."""
    if not path.is_absolute() or ".." in path.parts:
        raise RuntimeConfigurationError("CONFIGURATION_FILE_INVALID")
    try:
        for parent in reversed(path.parents):
            metadata = parent.lstat()
            if parent.is_symlink() or parent.is_junction() or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeConfigurationError("CONFIGURATION_FILE_INVALID")
        metadata = path.lstat()
        if path.is_symlink() or path.is_junction() or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeConfigurationError("CONFIGURATION_FILE_INVALID")
        return metadata
    except OSError:
        raise RuntimeConfigurationError("CONFIGURATION_FILE_INVALID") from None


def _read_regular_file(path: Path, maximum: int) -> bytes:
    metadata = _guard_file(path)
    if not 0 < metadata.st_size <= maximum:
        raise RuntimeConfigurationError("CONFIGURATION_FILE_INVALID")
    descriptor: int | None = None
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_BINARY", 0)
        )
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ) != (metadata.st_dev, metadata.st_ino, metadata.st_size):
            raise RuntimeConfigurationError("CONFIGURATION_FILE_INVALID")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            contents = handle.read(maximum + 1)
            final = os.fstat(handle.fileno())
        current = _guard_file(path)
        if (
            not 0 < len(contents) <= maximum
            or len(contents) != opened.st_size
            or (
                final.st_dev,
                final.st_ino,
                final.st_size,
                final.st_mtime_ns,
            )
            != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        ):
            raise RuntimeConfigurationError("CONFIGURATION_FILE_INVALID")
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ):
            raise RuntimeConfigurationError("CONFIGURATION_FILE_INVALID")
        return contents
    except OSError:
        raise RuntimeConfigurationError("CONFIGURATION_FILE_INVALID") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise RuntimeConfigurationError("CONFIGURATION_INVALID")
        result[name] = value
    return result


def _invalid_constant(value: str) -> object:
    raise RuntimeConfigurationError("CONFIGURATION_INVALID")


def load_runtime_configuration(path: Path) -> ParserRuntimeConfiguration:
    """Load one explicitly supplied application-owned file, bounded to 64 KiB.

    The application controls this absolute path and its ancestors. Filesystem
    shape checks cannot establish that a user selected or approved a descriptor.
    There is no environment lookup, search path, cached configuration or fallback.
    """
    contents = _read_regular_file(path, MAX_DESCRIPTOR_BYTES)
    try:
        value: object = json.loads(
            contents, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
        return ParserRuntimeConfiguration.model_validate(value)
    except (UnicodeError, ValueError, ValidationError, RecursionError):
        raise RuntimeConfigurationError("CONFIGURATION_INVALID") from None


def current_runtime_code_hashes() -> RuntimeCodeHashes:
    """Hash fixed installed application modules without importing the parser SDK."""
    directory = Path(__file__).absolute().parent
    return RuntimeCodeHashes(
        adapter_code_sha256=hashlib.sha256(
            _read_regular_file(directory / "adapter.py", MAX_CODE_BYTES)
        ).hexdigest(),
        geometry_code_sha256=hashlib.sha256(
            _read_regular_file(directory / "geometry.py", MAX_CODE_BYTES)
        ).hexdigest(),
        sdk_code_sha256=hashlib.sha256(
            _read_regular_file(directory / "sdk.py", MAX_CODE_BYTES)
        ).hexdigest(),
        artifact_models_code_sha256=hashlib.sha256(
            _read_regular_file(directory / "models.py", MAX_CODE_BYTES)
        ).hexdigest(),
    )


def _sdk_identity(configuration: Mapping[str, object]) -> dict[str, str]:
    try:
        value = dict(configuration)
        if set(value) != {
            "adapter",
            "backend",
            "backend_code_sha256",
            "packages",
            "package_manifest_sha256",
            "model_manifest_sha256",
            "pipeline_options",
            "configuration_sha256",
        } or (
            value["adapter"] != "regintel-docling-v1"
            or value["backend"] != "ThreadedDoclingParseDocumentBackend"
            or not isinstance(value["pipeline_options"], dict)
        ):
            raise ValueError
        retained = {name: item for name, item in value.items() if name != "configuration_sha256"}
        canonical = _canonical_bytes(retained, "SDK_CONFIGURATION_INVALID")
        if len(canonical) > MAX_DESCRIPTOR_BYTES:
            raise ValueError
        if value["configuration_sha256"] != hashlib.sha256(canonical).hexdigest():
            raise ValueError
        raw_packages = value["packages"]
        if not isinstance(raw_packages, list) or not 1 <= len(raw_packages) <= 256:
            raise ValueError
        packages = tuple(PackageVersion.model_validate(package) for package in raw_packages)
        names = tuple(package.name for package in packages)
        if names != tuple(sorted(set(names))) or "docling-parse" not in names:
            raise ValueError
        if value["package_manifest_sha256"] != package_manifest_sha256(packages):
            raise ValueError
        hash_validator = TypeAdapter(Sha256Hash)
        return {
            name: hash_validator.validate_python(value[name])
            for name in (
                "configuration_sha256",
                "model_manifest_sha256",
                "package_manifest_sha256",
                "backend_code_sha256",
            )
        }
    except (KeyError, TypeError, ValueError, ValidationError):
        raise RuntimeConfigurationError("SDK_CONFIGURATION_INVALID") from None


def build_runtime_configuration(
    *,
    resolved_sdk_configuration: Mapping[str, object],
    coordinate_frame: SelectedCoordinateFrame,
    code_hashes: RuntimeCodeHashes,
    source_limits: SourceLimits = DEFAULT_SOURCE_LIMITS,
) -> ParserRuntimeConfiguration:
    """Build a descriptor for explicit review; this does not approve the selection."""
    identity = _sdk_identity(resolved_sdk_configuration)
    try:
        return ParserRuntimeConfiguration.model_validate(
            code_hashes.model_dump(mode="python")
            | {
                "coordinate_frame": coordinate_frame,
                "source_limits": source_limits.model_dump(mode="python"),
                "sdk_configuration_sha256": identity["configuration_sha256"],
                "model_manifest_sha256": identity["model_manifest_sha256"],
                "package_manifest_sha256": identity["package_manifest_sha256"],
                "backend_code_sha256": identity["backend_code_sha256"],
            }
        )
    except (AttributeError, ValidationError):
        raise RuntimeConfigurationError("CONFIGURATION_INVALID") from None


def _validate_installed_code(configuration: ParserRuntimeConfiguration) -> None:
    actual = current_runtime_code_hashes().model_dump(mode="python")
    if any(getattr(configuration, name) != expected for name, expected in actual.items()):
        raise RuntimeConfigurationError("RUNTIME_CONFIGURATION_MISMATCH")


def validate_runtime_configuration(
    configuration: ParserRuntimeConfiguration,
    *,
    resolved_sdk_configuration: Mapping[str, object],
) -> str:
    """Require the selected descriptor, actual installed code and resolved SDK to agree."""
    configuration = _validated_descriptor(configuration)
    _validate_installed_code(configuration)
    identity = _sdk_identity(resolved_sdk_configuration)
    if any(
        getattr(configuration, descriptor_name) != identity[sdk_name]
        for descriptor_name, sdk_name in (
            ("sdk_configuration_sha256", "configuration_sha256"),
            ("model_manifest_sha256", "model_manifest_sha256"),
            ("package_manifest_sha256", "package_manifest_sha256"),
            ("backend_code_sha256", "backend_code_sha256"),
        )
    ):
        raise RuntimeConfigurationError("RUNTIME_CONFIGURATION_MISMATCH")
    return configuration.processing_configuration_sha256


def validate_artifact_provenance(
    configuration: ParserRuntimeConfiguration, *, provenance: ParseProvenance
) -> str:
    """Reject artifacts from another frame, SDK identity or application adapter."""
    configuration = _validated_descriptor(configuration)
    _validate_installed_code(configuration)
    try:
        provenance = ParseProvenance.model_validate(provenance.model_dump(mode="python"))
    except (AttributeError, ValidationError):
        raise RuntimeConfigurationError("ARTIFACT_PROVENANCE_MISMATCH") from None
    if any(
        getattr(configuration, descriptor_name) != getattr(provenance, provenance_name)
        for descriptor_name, provenance_name in (
            ("adapter_name", "adapter_name"),
            ("adapter_version", "adapter_version"),
            ("adapter_code_sha256", "adapter_code_sha256"),
            ("coordinate_frame", "coordinate_frame"),
            ("sdk_configuration_sha256", "configuration_sha256"),
            ("model_manifest_sha256", "model_manifest_sha256"),
            ("package_manifest_sha256", "package_manifest_sha256"),
            ("backend_code_sha256", "backend_code_sha256"),
        )
    ):
        raise RuntimeConfigurationError("ARTIFACT_PROVENANCE_MISMATCH")
    if provenance.backend_name != "ThreadedDoclingParseDocumentBackend":
        raise RuntimeConfigurationError("ARTIFACT_PROVENANCE_MISMATCH")
    versions = {package.name: package.version for package in provenance.packages}
    if provenance.backend_version != versions.get("docling-parse"):
        raise RuntimeConfigurationError("ARTIFACT_PROVENANCE_MISMATCH")
    return configuration.processing_configuration_sha256
