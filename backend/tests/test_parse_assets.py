"""Model acquisition uses mocked public bytes; offline checks never access a network."""

import hashlib
import json
import os
import stat
import urllib.request
from dataclasses import dataclass, replace
from http.client import HTTPMessage
from io import BytesIO
from pathlib import Path
from typing import Self

import pytest

from regintel.parsing import assets


class PublicResponse(BytesIO):
    def __init__(self, data: bytes, url: str) -> None:
        super().__init__(data)
        self.url = url

    def __enter__(self) -> Self:
        return self


@dataclass
class Catalogue:
    root: Path
    specs: tuple[assets.AssetSpec, ...]
    bodies: dict[str, bytes]
    requests: list[urllib.request.Request]


@dataclass
class MockFilesystem:
    f_flag: int


@pytest.fixture
def catalogue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Catalogue:
    weights = b"public mocked model weights"
    specs = (
        assets.AssetSpec(
            "engine/model.bin",
            "https://public.example/model",
            "frozen-revision",
            "Apache-2.0",
            len(weights),
            hashlib.sha256(weights).hexdigest(),
            100,
        ),
        assets.AssetSpec(
            "engine/config.json",
            "https://public.example/config",
            "frozen-revision",
            "Apache-2.0",
            max_bytes=100,
        ),
    )
    result = Catalogue(
        tmp_path / "models", specs, {specs[0].url: weights, specs[1].url: b'{"model":"tiny"}'}, []
    )
    monkeypatch.setattr(assets, "ASSETS", specs)

    class Opener:
        def open(self, request: urllib.request.Request, *, timeout: int) -> PublicResponse:
            assert timeout == 90
            assert not request.has_header("Authorization")
            assert not request.has_header("Cookie")
            result.requests.append(request)
            return PublicResponse(result.bodies[request.full_url], request.full_url)

    def build_opener(*handlers: object) -> Opener:
        proxies = [
            handler for handler in handlers if isinstance(handler, urllib.request.ProxyHandler)
        ]
        assert len(proxies) == 1 and proxies[0].proxies == {}
        assert any(isinstance(handler, assets._HttpsRedirect) for handler in handlers)
        return Opener()

    monkeypatch.setattr(assets.urllib.request, "build_opener", build_opener)
    return result


def refuse_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline verification attempted network access")

    monkeypatch.setattr(assets.urllib.request, "build_opener", forbidden)


def test_anonymous_acquisition_and_offline_repeat_are_exact(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, sha256 = assets.acquire_models(catalogue.root)
    assert len(catalogue.requests) == 2
    assert tuple(record.path for record in manifest.assets) == tuple(
        spec.path for spec in catalogue.specs
    )
    for spec in catalogue.specs:
        assert (catalogue.root / spec.path).read_bytes() == catalogue.bodies[spec.url]
    refuse_network(monkeypatch)
    assert assets.verify_models(catalogue.root) == (manifest, sha256)
    assert assets.acquire_models(catalogue.root) == (manifest, sha256)
    (catalogue.root / "acquisition-receipt.json").write_text('{"arbitrary":"receipt"}')
    assert assets.verify_models(catalogue.root) == (manifest, sha256)
    assert not list(catalogue.root.rglob("*.part"))


@pytest.mark.parametrize("corruption", [b"", b"too short", b"x" * 101, b"x" * 27])
def test_bad_existing_weights_do_not_establish_manifest(
    catalogue: Catalogue,
    corruption: bytes,
) -> None:
    path = catalogue.root / catalogue.specs[0].path
    path.parent.mkdir(parents=True)
    path.write_bytes(corruption)
    with pytest.raises(ValueError):
        assets.acquire_models(catalogue.root)
    assert path.read_bytes() == corruption
    assert not (catalogue.root / assets.MANIFEST_NAME).exists()
    assert catalogue.requests == []


def test_valid_existing_weights_reused_but_unhashed_metadata_is_rechecked(
    catalogue: Catalogue,
) -> None:
    for spec in catalogue.specs:
        path = catalogue.root / spec.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(catalogue.bodies[spec.url])
    assets.acquire_models(catalogue.root)
    assert [request.full_url for request in catalogue.requests] == [catalogue.specs[1].url]


def test_unknown_existing_metadata_cannot_poison_manifest(catalogue: Catalogue) -> None:
    path = catalogue.root / catalogue.specs[1].path
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"model":"tampered"}')
    with pytest.raises(ValueError, match="Concurrent model acquisition differs"):
        assets.acquire_models(catalogue.root)
    assert path.read_bytes() == b'{"model":"tampered"}'
    assert not (catalogue.root / assets.MANIFEST_NAME).exists()
    assert not list(catalogue.root.rglob("*.part"))


@pytest.mark.parametrize("response", [b"", b"wrong", b"x" * 101, b"x" * 27])
def test_invalid_downloads_publish_no_weights_or_manifest(
    catalogue: Catalogue,
    response: bytes,
) -> None:
    catalogue.bodies[catalogue.specs[0].url] = response
    with pytest.raises(ValueError):
        assets.acquire_models(catalogue.root)
    assert not (catalogue.root / catalogue.specs[0].path).exists()
    assert not (catalogue.root / assets.MANIFEST_NAME).exists()
    assert not list(catalogue.root.rglob("*.part"))


def test_changed_bytes_after_acquisition_fail_offline(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets.acquire_models(catalogue.root)
    refuse_network(monkeypatch)
    path = catalogue.root / catalogue.specs[1].path
    path.write_bytes(b'{"model":"tinyX"}')
    with pytest.raises(ValueError, match="Model integrity failure"):
        assets.verify_models(catalogue.root)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "extra",
        "order",
        "path",
        "url",
        "revision",
        "license",
        "sha256",
        "byte_size",
        "unknown",
    ],
)
def test_manifest_rejects_changed_catalogue_and_integrity(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    assets.acquire_models(catalogue.root)
    refuse_network(monkeypatch)
    path = catalogue.root / assets.MANIFEST_NAME
    data = json.loads(path.read_bytes())
    if change == "missing":
        data["assets"].pop()
    elif change == "extra":
        data["assets"].append(data["assets"][0])
    elif change == "order":
        data["assets"].reverse()
    elif change == "unknown":
        data["unknown"] = "forbidden"
    else:
        data["assets"][0][change] = (
            "0" * 64 if change == "sha256" else 42 if change == "byte_size" else "altered"
        )
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        assets.verify_models(catalogue.root)


def test_mutually_modified_weight_and_manifest_still_require_publisher_hash(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets.acquire_models(catalogue.root)
    refuse_network(monkeypatch)
    wrong = b"x" * len(catalogue.bodies[catalogue.specs[0].url])
    (catalogue.root / catalogue.specs[0].path).write_bytes(wrong)
    path = catalogue.root / assets.MANIFEST_NAME
    data = json.loads(path.read_bytes())
    data["assets"][0]["sha256"] = hashlib.sha256(wrong).hexdigest()
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Publisher hash mismatch"):
        assets.verify_models(catalogue.root)


@pytest.mark.parametrize(
    "relative",
    [
        "../escape",
        "/absolute",
        "a/../../escape",
        "a\\escape",
        "C:/escape",
        "a/stream:ads",
        "a//b",
        "a/./b",
        "",
    ],
)
def test_catalogue_path_confinement(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
) -> None:
    monkeypatch.setattr(assets, "ASSETS", (replace(catalogue.specs[0], path=relative),))
    with pytest.raises(ValueError, match="Model path escapes"):
        assets.acquire_models(catalogue.root)
    assert catalogue.requests == []


def test_relative_root_is_rejected() -> None:
    with pytest.raises(ValueError, match="absolute"):
        assets.acquire_models(Path("models"))
    with pytest.raises(ValueError, match="absolute"):
        assets.verify_models(Path("models"))


@pytest.mark.parametrize(
    "location", ["ancestor", "root", "directory", "file", "manifest", "receipt"]
)
def test_junctions_are_rejected_before_read_write_or_network(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    catalogue.root.mkdir()
    suspect = {
        "ancestor": catalogue.root.parent,
        "root": catalogue.root,
        "directory": catalogue.root / "engine",
        "file": catalogue.root / catalogue.specs[0].path,
        "manifest": catalogue.root / assets.MANIFEST_NAME,
        "receipt": catalogue.root / "acquisition-receipt.json",
    }[location]
    original = Path.is_junction

    def junction(path: Path) -> bool:
        return path == suspect or original(path)

    monkeypatch.setattr(Path, "is_junction", junction)
    with pytest.raises(ValueError, match="symlinks/junctions"):
        assets.acquire_models(catalogue.root)
    if location != "receipt":
        assert catalogue.requests == []


def test_real_symlink_directory_cannot_escape(
    catalogue: Catalogue,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    catalogue.root.mkdir()
    try:
        (catalogue.root / "engine").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Host cannot create an unprivileged symlink: {error}")
    with pytest.raises(ValueError):
        assets.acquire_models(catalogue.root)
    assert catalogue.requests == []
    assert list(outside.iterdir()) == []


def test_directories_and_oversized_manifest_are_rejected_offline(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets.acquire_models(catalogue.root)
    refuse_network(monkeypatch)
    path = catalogue.root / assets.MANIFEST_NAME
    path.write_bytes(b"x" * (128 * 1024 + 1))
    with pytest.raises(ValueError, match="Oversized model manifest"):
        assets.verify_models(catalogue.root)
    path.unlink()
    path.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        assets.verify_models(catalogue.root)


def test_failed_manifest_publication_leaves_no_partial_final_or_temp(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = assets.os.link

    def broken(source: Path, target: Path) -> None:
        if target.name == assets.MANIFEST_NAME:
            assert not target.exists()
            assets.ModelManifest.model_validate_json(source.read_bytes())
            raise OSError("mocked publication failure")
        original(source, target)

    monkeypatch.setattr(assets.os, "link", broken)
    with pytest.raises(OSError, match="publication failure"):
        assets.acquire_models(catalogue.root)
    assert not (catalogue.root / assets.MANIFEST_NAME).exists()
    assert not list(catalogue.root.rglob("*.part"))


@pytest.mark.parametrize("same", [True, False])
def test_concurrent_asset_publication_accepts_only_identical_bytes(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
    same: bool,
) -> None:
    original = assets.os.link

    def winner(source: Path, target: Path) -> None:
        if target.name == "model.bin":
            target.write_bytes(source.read_bytes() if same else b"different winner")
            raise FileExistsError("mocked concurrent publication")
        original(source, target)

    monkeypatch.setattr(assets.os, "link", winner)
    if same:
        assets.acquire_models(catalogue.root)
    else:
        with pytest.raises(ValueError, match="Concurrent model acquisition differs"):
            assets.acquire_models(catalogue.root)
        assert not (catalogue.root / assets.MANIFEST_NAME).exists()
        assert (catalogue.root / catalogue.specs[0].path).read_bytes() == b"different winner"
    assert not list(catalogue.root.rglob("*.part"))


@pytest.mark.parametrize(
    "url",
    ["http://public.example/model", "https://user:pass@example/model", "https:///missing-host"],
)
def test_all_redirect_hops_must_remain_anonymous_https(url: str) -> None:
    handler = assets._HttpsRedirect()
    with pytest.raises(ValueError, match="anonymous HTTPS"):
        handler.redirect_request(
            urllib.request.Request("https://public.example/model"),
            BytesIO(),
            302,
            "Found",
            HTTPMessage(),
            url,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX umask and mode contract")
def test_restrictive_umask_still_creates_worker_readable_models(catalogue: Catalogue) -> None:
    previous = os.umask(0o077)
    try:
        assets.acquire_models(catalogue.root)
    finally:
        os.umask(previous)
    for path in (catalogue.root, *catalogue.root.rglob("*")):
        assert stat.S_IMODE(path.stat().st_mode) == (0o755 if path.is_dir() else 0o644)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_existing_manifest_cannot_mask_wrong_worker_permissions(catalogue: Catalogue) -> None:
    assets.acquire_models(catalogue.root)
    file_path = catalogue.root / catalogue.specs[0].path
    os.chmod(file_path, 0o600)
    with pytest.raises(ValueError, match="public read-only"):
        assets.verify_models(catalogue.root)
    os.chmod(file_path, 0o644)
    os.chmod(file_path.parent, 0o700)
    with pytest.raises(ValueError, match="worker read and traversal"):
        assets.verify_models(catalogue.root)


def exposed_posix_mount(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
    *,
    readonly: bool,
    synthetic_modes: bool = True,
    inaccessible: Path | None = None,
    writable_child: Path | None = None,
    unavailable: bool = False,
) -> list[tuple[Path, int]]:
    """Mock kernel metadata/access, leaving actual file reads and hashes in place."""
    original_stat = Path.stat
    accesses: list[tuple[Path, int]] = []

    def exposed_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        actual = original_stat(path, follow_symlinks=follow_symlinks)
        if path.is_relative_to(catalogue.root):
            values = list(actual)
            mode = 0o777 if synthetic_modes else (0o755 if stat.S_ISDIR(actual.st_mode) else 0o644)
            values[0] = stat.S_IFMT(actual.st_mode) | mode
            return os.stat_result(values)
        return actual

    def filesystem(path: Path) -> MockFilesystem:
        if unavailable:
            raise OSError("mocked unavailable mount metadata")
        return MockFilesystem(1 if readonly and path != writable_child else 0)

    def access(path: Path, mode: int) -> bool:
        accesses.append((path, mode))
        return path != inaccessible

    monkeypatch.setattr(Path, "stat", exposed_stat)
    monkeypatch.setattr(assets.os, "statvfs", filesystem, raising=False)
    monkeypatch.setattr(assets.os, "ST_RDONLY", 1, raising=False)
    monkeypatch.setattr(assets.os, "access", access)
    # Exercise the POSIX branch on Windows without changing global os.name or Path flavour.
    monkeypatch.setattr(assets, "_validate_modes", assets._validate_posix_modes)
    return accesses


def test_readonly_synthetic_modes_allow_offline_verification_without_chmod(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = assets.acquire_models(catalogue.root)
    refuse_network(monkeypatch)
    accesses = exposed_posix_mount(catalogue, monkeypatch, readonly=True)

    def forbid_chmod(*args: object, **kwargs: object) -> None:
        raise AssertionError("verification attempted to change read-only mount permissions")

    monkeypatch.setattr(assets.os, "chmod", forbid_chmod)
    assert assets.verify_models(catalogue.root) == expected
    assert (catalogue.root / assets.MANIFEST_NAME, os.R_OK) in accesses
    assert (catalogue.root, os.R_OK | os.X_OK) in accesses
    assert (catalogue.root / "engine", os.R_OK | os.X_OK) in accesses
    for spec in catalogue.specs:
        assert (catalogue.root / spec.path, os.R_OK) in accesses


@pytest.mark.parametrize("readonly,unavailable", [(False, False), (True, True)])
def test_synthetic_modes_require_kernel_readonly_proof(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
    readonly: bool,
    unavailable: bool,
) -> None:
    assets.acquire_models(catalogue.root)
    refuse_network(monkeypatch)
    exposed_posix_mount(catalogue, monkeypatch, readonly=readonly, unavailable=unavailable)
    with pytest.raises(ValueError, match="public read-only"):
        assets.verify_models(catalogue.root)


@pytest.mark.parametrize("location", ["file", "directory", "root"])
def test_readonly_mount_does_not_hide_unavailable_worker_access(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    assets.acquire_models(catalogue.root)
    refuse_network(monkeypatch)
    inaccessible = {
        "file": catalogue.root / catalogue.specs[0].path,
        "directory": catalogue.root / "engine",
        "root": catalogue.root,
    }[location]
    exposed_posix_mount(catalogue, monkeypatch, readonly=True, inaccessible=inaccessible)
    with pytest.raises(ValueError, match="current worker|worker read and traversal"):
        assets.verify_models(catalogue.root)


def test_readonly_root_does_not_approve_a_nested_writable_model_path(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets.acquire_models(catalogue.root)
    refuse_network(monkeypatch)
    exposed_posix_mount(
        catalogue,
        monkeypatch,
        readonly=True,
        writable_child=catalogue.root / catalogue.specs[0].path,
    )
    with pytest.raises(ValueError, match="public read-only"):
        assets.verify_models(catalogue.root)


def test_readonly_mount_exception_retains_actual_byte_integrity_checks(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets.acquire_models(catalogue.root)
    (catalogue.root / catalogue.specs[1].path).write_bytes(b"tampered metadata")
    refuse_network(monkeypatch)
    exposed_posix_mount(catalogue, monkeypatch, readonly=True)
    with pytest.raises(ValueError, match="Model integrity failure"):
        assets.verify_models(catalogue.root)


def test_exact_posix_permissions_remain_valid_on_writable_filesystem(
    catalogue: Catalogue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = assets.acquire_models(catalogue.root)
    refuse_network(monkeypatch)
    exposed_posix_mount(catalogue, monkeypatch, readonly=False, synthetic_modes=False)
    assert assets.verify_models(catalogue.root) == expected
