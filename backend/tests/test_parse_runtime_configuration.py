"""Explicit parser selection must agree with code, SDK identity and artifact provenance."""

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from regintel.parsing import configuration as runtime
from regintel.parsing.configuration import (
    MAX_DESCRIPTOR_BYTES,
    MAX_SOURCE_BYTES,
    MAX_SOURCE_PAGES,
    ParserRuntimeConfiguration,
    RuntimeCodeHashes,
    RuntimeConfigurationError,
    SourceLimits,
    build_runtime_configuration,
    canonical_configuration_bytes,
    current_runtime_code_hashes,
    load_runtime_configuration,
    validate_artifact_provenance,
    validate_runtime_configuration,
)
from regintel.parsing.models import PackageVersion, ParseProvenance, package_manifest_sha256


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sdk_configuration() -> dict[str, object]:
    packages = (PackageVersion(name="docling-parse", version="7.22.1"),)
    value: dict[str, object] = {
        "adapter": "regintel-docling-v1",
        "backend": "ThreadedDoclingParseDocumentBackend",
        "backend_code_sha256": "b" * 64,
        "packages": [package.model_dump(mode="json") for package in packages],
        "package_manifest_sha256": package_manifest_sha256(packages),
        "model_manifest_sha256": "c" * 64,
        "pipeline_options": {"accelerator_options": {"device": "cpu", "num_threads": 2}},
    }
    value["configuration_sha256"] = hashlib.sha256(canonical(value)).hexdigest()
    return value


def descriptor() -> ParserRuntimeConfiguration:
    return build_runtime_configuration(
        resolved_sdk_configuration=sdk_configuration(),
        coordinate_frame="CROP_ROTATED_TOP_LEFT",
        code_hashes=current_runtime_code_hashes(),
    )


def provenance(configuration: ParserRuntimeConfiguration) -> ParseProvenance:
    packages = (PackageVersion(name="docling-parse", version="7.22.1"),)
    return ParseProvenance(
        adapter_name=configuration.adapter_name,
        adapter_version=configuration.adapter_version,
        adapter_code_sha256=configuration.adapter_code_sha256,
        backend_name="ThreadedDoclingParseDocumentBackend",
        backend_version="7.22.1",
        backend_code_sha256=configuration.backend_code_sha256,
        coordinate_frame=configuration.coordinate_frame,
        packages=packages,
        package_manifest_sha256=configuration.package_manifest_sha256,
        configuration_sha256=configuration.sdk_configuration_sha256,
        model_manifest_sha256=configuration.model_manifest_sha256,
    )


def test_selected_runtime_and_artifact_agree_and_descriptor_loads(tmp_path: Path) -> None:
    selected = descriptor()
    path = tmp_path / "selected-parser.json"
    path.write_bytes(canonical_configuration_bytes(selected))
    loaded = load_runtime_configuration(path)
    assert loaded == selected
    assert (
        validate_runtime_configuration(loaded, resolved_sdk_configuration=sdk_configuration())
        == selected.processing_configuration_sha256
    )
    assert (
        validate_artifact_provenance(loaded, provenance=provenance(selected))
        == selected.processing_configuration_sha256
    )
    assert len(selected.processing_configuration_sha256) == 64
    assert "processing_configuration_sha256" not in json.loads(path.read_bytes())


def test_installed_code_is_hashed_without_importing_its_modules() -> None:
    code = current_runtime_code_hashes()
    directory = Path(runtime.__file__).parent
    for field, filename in (
        ("adapter_code_sha256", "adapter.py"),
        ("geometry_code_sha256", "geometry.py"),
        ("sdk_code_sha256", "sdk.py"),
        ("artifact_models_code_sha256", "models.py"),
    ):
        expected = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
        assert getattr(code, field) == expected


def test_native_configuration_import_never_loads_heavy_sdk() -> None:
    script = """
import builtins
import sys
original_import = builtins.__import__
forbidden = {'docling', 'docling_core', 'docling_parse', 'docling_ibm_models',
             'rapidocr', 'torch', 'torchvision', 'onnxruntime', 'cv2', 'scipy', 'rtree'}
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in forbidden or name in {'regintel.parsing.sdk',
                                                  'regintel.parsing.adapter'}:
        raise AssertionError('Optional parser imported')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
from regintel.parsing.configuration import current_runtime_code_hashes
current_runtime_code_hashes()
assert not forbidden.intersection(name.split('.')[0] for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("coordinate_frame", "RAW_PDF_BOTTOM_LEFT"),
        ("sdk_configuration_sha256", "1" * 64),
        ("model_manifest_sha256", "1" * 64),
        ("package_manifest_sha256", "1" * 64),
        ("backend_code_sha256", "1" * 64),
        ("adapter_code_sha256", "1" * 64),
        ("geometry_code_sha256", "1" * 64),
        ("sdk_code_sha256", "1" * 64),
        ("artifact_models_code_sha256", "1" * 64),
        ("source_limits", {"max_file_bytes": 1024, "max_pages": 1}),
    ],
)
def test_processing_identity_binds_selected_frame_limits_and_every_hash(
    field: str, value: object
) -> None:
    original = descriptor()
    changed = ParserRuntimeConfiguration.model_validate(
        original.model_dump(mode="python") | {field: value}
    )
    assert original.processing_configuration_sha256 != changed.processing_configuration_sha256


def test_dictionary_order_has_no_effect_on_processing_identity() -> None:
    sdk = sdk_configuration()
    sdk = dict(reversed(list(sdk.items())))
    changed = build_runtime_configuration(
        resolved_sdk_configuration=sdk,
        coordinate_frame="CROP_ROTATED_TOP_LEFT",
        code_hashes=current_runtime_code_hashes(),
    )
    assert changed == descriptor()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2.0.0"),
        ("adapter_name", "another-adapter"),
        ("adapter_version", "latest"),
        ("coordinate_frame", None),
        ("coordinate_frame", "AUTO"),
        ("sdk_code_sha256", "A" * 64),
        ("sdk_code_sha256", "abc"),
        ("approved", True),
        ("path", "D:/unexpected/.env"),
        ("credential", "untrusted"),
        ("processing_configuration_sha256", "1" * 64),
    ],
)
def test_descriptor_rejects_unknown_selection_and_identity_overrides(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        ParserRuntimeConfiguration.model_validate(descriptor().model_dump() | {field: value})


@pytest.mark.parametrize("value", [0, -1, MAX_SOURCE_BYTES + 1, True, "1024", 1024.0])
def test_source_size_limit_is_an_explicit_bounded_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        SourceLimits.model_validate({"max_file_bytes": value})


@pytest.mark.parametrize("value", [0, -1, MAX_SOURCE_PAGES + 1, True, "20", 20.0])
def test_source_page_limit_is_an_explicit_bounded_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        SourceLimits.model_validate({"max_pages": value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter", "injected"),
        ("backend", "OtherBackend"),
        ("backend_code_sha256", "invalid"),
        ("model_manifest_sha256", "invalid"),
        ("package_manifest_sha256", "0" * 64),
        ("packages", []),
        ("packages", [{"name": "other", "version": "1"}]),
        ("pipeline_options", None),
        ("pipeline_options", {"value": float("nan")}),
        ("secret", "must not enter the descriptor"),
    ],
)
def test_even_internally_rehashed_invalid_sdk_cannot_build_a_descriptor(
    field: str, value: object
) -> None:
    sdk = sdk_configuration() | {field: value}
    # Attackers can hash their own data. Internal consistency is not acceptance.
    retained = {name: item for name, item in sdk.items() if name != "configuration_sha256"}
    try:
        sdk["configuration_sha256"] = hashlib.sha256(canonical(retained)).hexdigest()
    except ValueError:
        pass
    with pytest.raises(RuntimeConfigurationError, match="SDK_CONFIGURATION_INVALID"):
        build_runtime_configuration(
            resolved_sdk_configuration=sdk,
            coordinate_frame="CROP_ROTATED_TOP_LEFT",
            code_hashes=current_runtime_code_hashes(),
        )


def test_sdk_configuration_is_verified_before_it_is_used() -> None:
    sdk = sdk_configuration()
    sdk["pipeline_options"] = {"accelerator_options": {"device": "cuda"}}
    with pytest.raises(RuntimeConfigurationError, match="SDK_CONFIGURATION_INVALID"):
        validate_runtime_configuration(descriptor(), resolved_sdk_configuration=sdk)


def test_self_consistent_new_sdk_settings_do_not_match_the_selected_descriptor() -> None:
    sdk = sdk_configuration()
    sdk["pipeline_options"] = {"accelerator_options": {"device": "cuda"}}
    retained = {name: item for name, item in sdk.items() if name != "configuration_sha256"}
    sdk["configuration_sha256"] = hashlib.sha256(canonical(retained)).hexdigest()
    with pytest.raises(RuntimeConfigurationError, match="RUNTIME_CONFIGURATION_MISMATCH"):
        validate_runtime_configuration(descriptor(), resolved_sdk_configuration=sdk)


def test_package_inventory_must_be_sorted_unique_and_match_its_own_hash() -> None:
    sdk = sdk_configuration()
    duplicate = [{"name": "docling-parse", "version": "7.22.1"}] * 2
    sdk["packages"] = duplicate
    sdk["package_manifest_sha256"] = package_manifest_sha256(
        tuple(PackageVersion.model_validate(item) for item in duplicate)
    )
    retained = {name: item for name, item in sdk.items() if name != "configuration_sha256"}
    sdk["configuration_sha256"] = hashlib.sha256(canonical(retained)).hexdigest()
    with pytest.raises(RuntimeConfigurationError, match="SDK_CONFIGURATION_INVALID"):
        build_runtime_configuration(
            resolved_sdk_configuration=sdk,
            coordinate_frame="CROP_ROTATED_TOP_LEFT",
            code_hashes=current_runtime_code_hashes(),
        )


@pytest.mark.parametrize(
    "field",
    [
        "adapter_code_sha256",
        "geometry_code_sha256",
        "sdk_code_sha256",
        "artifact_models_code_sha256",
    ],
)
def test_installed_application_code_drift_rejects_runtime_and_artifact(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = descriptor()
    modified = RuntimeCodeHashes.model_validate(
        current_runtime_code_hashes().model_dump() | {field: "0" * 64}
    )
    monkeypatch.setattr(runtime, "current_runtime_code_hashes", lambda: modified)
    with pytest.raises(RuntimeConfigurationError, match="RUNTIME_CONFIGURATION_MISMATCH"):
        validate_runtime_configuration(selected, resolved_sdk_configuration=sdk_configuration())
    with pytest.raises(RuntimeConfigurationError, match="RUNTIME_CONFIGURATION_MISMATCH"):
        validate_artifact_provenance(selected, provenance=provenance(selected))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("coordinate_frame", "RAW_PDF_BOTTOM_LEFT"),
        ("adapter_name", "another-adapter"),
        ("adapter_version", "9.0.0"),
        ("adapter_code_sha256", "0" * 64),
        ("configuration_sha256", "0" * 64),
        ("model_manifest_sha256", "0" * 64),
        ("backend_code_sha256", "0" * 64),
        ("backend_name", "another-backend"),
        ("backend_version", "9.0.0"),
        ("package_manifest_sha256", "0" * 64),
    ],
)
def test_artifact_from_another_processing_selection_cannot_be_used(
    field: str, value: object
) -> None:
    selected = descriptor()
    untrusted = provenance(selected).model_copy(update={field: value})
    with pytest.raises(RuntimeConfigurationError, match="ARTIFACT_PROVENANCE_MISMATCH"):
        validate_artifact_provenance(selected, provenance=untrusted)


@pytest.mark.parametrize(
    "contents",
    [
        b"{}",
        b"null",
        b"[]",
        b"{invalid",
        b"\xff",
        b'{"schema_version":"1.0.0","schema_version":"1.0.0"}',
        b'{"max_file_bytes":NaN}',
    ],
)
def test_loader_rejects_invalid_or_duplicate_json_without_echoing_input(
    contents: bytes, tmp_path: Path
) -> None:
    path = tmp_path / "selected.json"
    path.write_bytes(contents)
    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_configuration(path)
    assert str(error.value) == "CONFIGURATION_INVALID"
    assert str(path) not in str(error.value)


def test_loader_reads_only_the_explicit_absolute_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_FILE_INVALID"):
        load_runtime_configuration(Path("selected.json"))
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_FILE_INVALID"):
        load_runtime_configuration(tmp_path / "missing.json")
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_FILE_INVALID"):
        load_runtime_configuration(tmp_path)


@pytest.mark.parametrize("length", [0, MAX_DESCRIPTOR_BYTES + 1])
def test_loader_rejects_empty_or_oversized_file_before_json_decode(
    length: int, tmp_path: Path
) -> None:
    path = tmp_path / "selected.json"
    path.write_bytes(b" " * length)
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_FILE_INVALID"):
        load_runtime_configuration(path)


def test_loader_rejects_junction_in_any_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "directory" / "selected.json"
    path.parent.mkdir()
    path.write_bytes(canonical_configuration_bytes(descriptor()))
    original = Path.is_junction

    def junction(candidate: Path) -> bool:
        return candidate == path.parent or original(candidate)

    monkeypatch.setattr(Path, "is_junction", junction)
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_FILE_INVALID"):
        load_runtime_configuration(path)


@pytest.mark.parametrize("link_location", ["file", "ancestor"])
def test_loader_rejects_link_flag_even_when_target_is_regular(
    link_location: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "directory" / "selected.json"
    path.parent.mkdir()
    path.write_bytes(canonical_configuration_bytes(descriptor()))
    flagged = path if link_location == "file" else path.parent
    original = Path.is_symlink

    def linked(candidate: Path) -> bool:
        return candidate == flagged or original(candidate)

    monkeypatch.setattr(Path, "is_symlink", linked)
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_FILE_INVALID"):
        load_runtime_configuration(path)


def test_loader_rejects_non_directory_ancestor(tmp_path: Path) -> None:
    ancestor = tmp_path / "regular-file"
    ancestor.write_bytes(b"not a directory")
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_FILE_INVALID"):
        load_runtime_configuration(ancestor / "selected.json")


def test_loader_rejects_replaced_file_between_inspection_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "selected.json"
    replacement = tmp_path / "replacement.json"
    contents = canonical_configuration_bytes(descriptor())
    path.write_bytes(contents)
    replacement.write_bytes(contents)
    original = os.open

    def replaced(candidate: Path, flags: int) -> int:
        if candidate == path:
            replacement.replace(path)
        return original(candidate, flags)

    monkeypatch.setattr(os, "open", replaced)
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_FILE_INVALID"):
        load_runtime_configuration(path)


def test_unvalidated_model_copy_cannot_bypass_descriptor_limits() -> None:
    untrusted = descriptor().model_copy(update={"coordinate_frame": "AUTO"})
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_INVALID"):
        canonical_configuration_bytes(untrusted)


def test_builder_does_not_mutate_sdk_input_or_retain_sdk_paths() -> None:
    sdk = sdk_configuration()
    sdk["pipeline_options"] = {"artifacts_path": "/models", "ocr_options": {"path": "/models/ocr"}}
    retained = {name: item for name, item in sdk.items() if name != "configuration_sha256"}
    sdk["configuration_sha256"] = hashlib.sha256(canonical(retained)).hexdigest()
    original = deepcopy(sdk)
    built = build_runtime_configuration(
        resolved_sdk_configuration=sdk,
        coordinate_frame="CROP_ROTATED_TOP_LEFT",
        code_hashes=current_runtime_code_hashes(),
    )
    assert sdk == original
    rendered = canonical_configuration_bytes(built)
    assert b"/models" not in rendered and b"pipeline_options" not in rendered


def test_file_metadata_change_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "selected.json"
    path.write_bytes(canonical_configuration_bytes(descriptor()))
    original = runtime._guard_file
    original_times = path.stat()
    calls = 0

    def changed(candidate: Path) -> os.stat_result:
        nonlocal calls
        calls += 1
        if calls == 2:
            candidate.write_bytes(b"{}")
            # Size change must fail even when filesystem timestamp granularity
            # or a restored timestamp hides the mutation from mtime comparison.
            os.utime(candidate, ns=(original_times.st_atime_ns, original_times.st_mtime_ns))
        return original(candidate)

    monkeypatch.setattr(runtime, "_guard_file", changed)
    with pytest.raises(RuntimeConfigurationError, match="CONFIGURATION_FILE_INVALID"):
        load_runtime_configuration(path)
