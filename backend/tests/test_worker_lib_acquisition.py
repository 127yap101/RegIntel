"""Failure and replay boundaries for container-only Debian acquisition."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import lzma
import os
import subprocess
import sys
import urllib.error
import urllib.request
from http.client import HTTPMessage
from pathlib import Path
from types import ModuleType
from typing import Protocol

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


class NamedArtifact(Protocol):
    filename: str
    size_bytes: int
    sha256: str


@pytest.fixture
def acquisition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    name = "regintel_worker_lib_acquisition_tests"
    spec = importlib.util.spec_from_file_location(
        name, REPOSITORY / "scripts" / "acquire-worker-libs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    module.CACHE = tmp_path / ".cache" / "worker-debs"
    module.MANIFEST = tmp_path / "data" / "worker-runtime-libs.json"
    return module


def test_atomic_immutable_records_preserve_existing_bytes(acquisition: ModuleType) -> None:
    target = acquisition.MANIFEST
    acquisition.publish_bytes(target, b"original")
    original_time = target.stat().st_mtime_ns
    acquisition.publish_bytes(target, b"original")
    assert target.stat().st_mtime_ns == original_time
    with pytest.raises(ValueError, match="immutable acquisition record differs"):
        acquisition.publish_bytes(target, b"changed")
    assert target.read_bytes() == b"original"
    assert list(target.parent.glob("*.part")) == []


@pytest.mark.parametrize("same_bytes", [False, True])
def test_concurrent_publication_never_overwrites(
    acquisition: ModuleType, monkeypatch: pytest.MonkeyPatch, same_bytes: bool
) -> None:
    target = acquisition.MANIFEST
    actual_link = os.link
    winner = b"proposal" if same_bytes else b"other writer"

    def concurrent_link(source: Path, destination: Path) -> None:
        destination.write_bytes(winner)
        actual_link(source, destination)

    monkeypatch.setattr(acquisition.os, "link", concurrent_link)
    if same_bytes:
        acquisition.publish_bytes(target, b"proposal")
    else:
        with pytest.raises(ValueError, match="Concurrent acquisition published different bytes"):
            acquisition.publish_bytes(target, b"proposal")
    assert target.read_bytes() == winner
    assert not list(target.parent.glob(".*.part"))


def test_directory_alias_is_rejected_before_artifact_write(acquisition: ModuleType) -> None:
    outside = acquisition.ROOT / "outside"
    outside.mkdir()
    try:
        (acquisition.ROOT / ".cache").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows does not permit symbolic-link creation in this test account")
    with pytest.raises(ValueError, match="link or junction"):
        acquisition.publish_bytes(acquisition.CACHE / "SHA256SUMS", b"value")
    assert not list(outside.iterdir())


def test_record_alias_cannot_modify_other_file(acquisition: ModuleType) -> None:
    acquisition.MANIFEST.parent.mkdir()
    original = acquisition.ROOT / "other.json"
    original.write_bytes(b"preserve")
    try:
        acquisition.MANIFEST.symlink_to(original)
    except OSError:
        pytest.skip("Windows does not permit symbolic-link creation in this test account")
    with pytest.raises(ValueError, match="link or junction"):
        acquisition.publish_bytes(acquisition.MANIFEST, b"changed")
    assert original.read_bytes() == b"preserve"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_directory_junction_cannot_redirect_acquisition(acquisition: ModuleType) -> None:
    outside = acquisition.ROOT / "outside"
    outside.mkdir()
    result = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(acquisition.ROOT / ".cache"), str(outside)],
        capture_output=True,
        text=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr
    assert (acquisition.ROOT / ".cache").is_junction()
    with pytest.raises(ValueError, match="link or junction"):
        acquisition.publish_bytes(acquisition.CACHE / "SHA256SUMS", b"changed")
    assert not list(outside.iterdir())


def test_directory_parent_that_is_a_file_is_preserved(acquisition: ModuleType) -> None:
    parent = acquisition.ROOT / ".cache"
    parent.write_bytes(b"user file")
    with pytest.raises(ValueError, match="not a directory"):
        acquisition.publish_bytes(acquisition.CACHE / "SHA256SUMS", b"value")
    assert parent.read_bytes() == b"user file"


def test_outside_workspace_is_rejected_before_creation(acquisition: ModuleType) -> None:
    with pytest.raises(ValueError, match="outside the project workspace"):
        acquisition.publish_bytes(acquisition.ROOT.parent / "outside.json", b"value")


def test_https_client_does_not_discover_environment_proxy_credentials(
    acquisition: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_discovery() -> None:
        raise AssertionError("Environment proxy lookup must not occur")

    monkeypatch.setattr(urllib.request, "getproxies", forbidden_discovery)
    assert isinstance(acquisition.https_client(), urllib.request.OpenerDirector)


@pytest.mark.parametrize(
    "url",
    [
        "http://mirrors.edge.kernel.org/debian/file",
        "https://other.example/debian/file",
        "https://user:password@mirrors.edge.kernel.org/debian/file",
        "https://mirrors.edge.kernel.org:8443/debian/file",
        "https://mirrors.edge.kernel.org/private/file",
        "https://mirrors.edge.kernel.org/debian/file?token=value",
        "https://mirrors.edge.kernel.org/debian/file#fragment",
        "https://mirrors.edge.kernel.org/debian/../private/file",
        "https://mirrors.edge.kernel.org/debian/%2e%2e/private/file",
        "https://mirrors.edge.kernel.org/debian/file\n",
    ],
)
def test_redirect_cannot_leave_public_verified_https_mirror(
    acquisition: ModuleType, url: str
) -> None:
    request = urllib.request.Request(f"{acquisition.MIRROR}/file")
    with pytest.raises(urllib.error.URLError, match="approved HTTPS mirror"):
        acquisition.RestrictedRedirect().redirect_request(
            request, io.BytesIO(), 302, "redirect", HTTPMessage(), url
        )


class FakeResponse(io.BytesIO):
    def __init__(self, url: str, data: bytes) -> None:
        super().__init__(data)
        self.url = url


class FakeClient:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls = 0

    def open(self, url: str, timeout: int) -> FakeResponse:
        assert timeout == 60
        self.calls += 1
        return FakeResponse(url, self.data)


@pytest.mark.parametrize("data", [b"ab", b"abcd", b"bad"])
def test_download_rejects_truncation_oversize_and_hash_mismatch(
    acquisition: ModuleType, monkeypatch: pytest.MonkeyPatch, data: bytes
) -> None:
    client = FakeClient(data)
    monkeypatch.setattr(acquisition, "https_client", lambda: client)
    artifact = acquisition.Artifact(
        "required.deb",
        f"{acquisition.MIRROR}/pool/required.deb",
        3,
        hashlib.sha256(b"abc").hexdigest(),
    )
    with pytest.raises(ValueError):
        acquisition.download(artifact)
    assert not (acquisition.CACHE / "required.deb").exists()
    assert not list(acquisition.CACHE.glob(".*.part"))


def test_verified_cached_download_never_reopens_network(
    acquisition: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient(b"abc")
    monkeypatch.setattr(acquisition, "https_client", lambda: client)
    artifact = acquisition.Artifact(
        "required.deb",
        f"{acquisition.MIRROR}/pool/required.deb",
        3,
        hashlib.sha256(b"abc").hexdigest(),
    )
    target = acquisition.download(artifact)
    assert target.read_bytes() == b"abc"
    acquisition.download(artifact)
    assert client.calls == 1


def test_bounded_decompression_rejects_large_and_trailing_streams(
    acquisition: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(acquisition, "MAX_INDEX_BYTES", 64)
    assert acquisition.bounded_index(lzma.compress(b"x" * 64)) == b"x" * 64
    with pytest.raises(ValueError, match="parse bound"):
        acquisition.bounded_index(lzma.compress(b"x" * 65))
    with pytest.raises(ValueError, match="parse bound"):
        acquisition.bounded_index(lzma.compress(b"x") + lzma.compress(b"y"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "changed"),
        ("architecture", "arm64"),
        ("base_image", "python:latest"),
        ("mirror", "https://other.example"),
        ("root_packages", ["unrelated-package"]),
    ],
)
def test_manifest_rejects_changed_frozen_identity(
    acquisition: ModuleType, field: str, value: object
) -> None:
    manifest = json.loads((REPOSITORY / "data" / "worker-runtime-libs.json").read_text())
    manifest[field] = value
    with pytest.raises(ValueError, match="acquisition identity differs"):
        acquisition.frozen_manifest(manifest)


def test_manifest_rejects_duplicate_package_records(acquisition: ModuleType) -> None:
    manifest = json.loads((REPOSITORY / "data" / "worker-runtime-libs.json").read_text())
    manifest["packages"].append(manifest["packages"][0])
    with pytest.raises(ValueError, match="duplicated"):
        acquisition.frozen_manifest(manifest)


def test_manifest_rejects_wrong_metadata_url(acquisition: ModuleType) -> None:
    manifest = json.loads((REPOSITORY / "data" / "worker-runtime-libs.json").read_text())
    manifest["metadata"][1]["url"] = f"{acquisition.MIRROR}/different-index"
    with pytest.raises(ValueError, match="metadata identity differs"):
        acquisition.frozen_manifest(manifest)


def test_release_rejects_different_archive_identity(acquisition: ModuleType) -> None:
    with pytest.raises(ValueError, match="not Debian Bookworm"):
        acquisition.release_index("Origin: Other\nCodename: bookworm\nSHA256:\n")


def test_signature_verifier_returns_only_successfully_verified_plaintext(
    acquisition: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed_plaintext = "Origin: Debian\nCodename: bookworm\n"
    commands: list[list[str]] = []

    def fake_docker(arguments: list[str]) -> str:
        commands.append(arguments)
        return signed_plaintext

    monkeypatch.setattr(acquisition, "docker", fake_docker)
    assert acquisition.verify_release() == signed_plaintext
    assert commands == [
        [
            "gpgv",
            "--output",
            "-",
            "--keyring",
            "/usr/share/keyrings/debian-archive-keyring.gpg",
            "/input/bookworm.InRelease",
        ]
    ]


@pytest.mark.parametrize("outside", ["prefix", "suffix"])
def test_raw_signed_envelope_cannot_supply_release_fields(
    acquisition: ModuleType, outside: str
) -> None:
    unsigned_fields = (
        f"Origin: Debian\nCodename: bookworm\nSHA256:\n {'f' * 64} 1 {acquisition.INDEX_PATH}\n"
    )
    envelope = "-----BEGIN PGP SIGNED MESSAGE-----\n-----END PGP SIGNATURE-----\n"
    value = unsigned_fields + envelope if outside == "prefix" else envelope + unsigned_fields
    with pytest.raises(ValueError, match="signature-verified release plaintext"):
        acquisition.release_index(value)


@pytest.mark.parametrize("outside", ["prefix", "suffix"])
@pytest.mark.parametrize("replay", [False, True])
def test_acquisition_ignores_unsigned_prefix_and_suffix_fields(
    acquisition: ModuleType, monkeypatch: pytest.MonkeyPatch, outside: str, replay: bool
) -> None:
    # This test isolates the verifier-output boundary. Actual Debian signature
    # validation is checked separately by the real offline acquisition probe.
    manifest = json.loads((REPOSITORY / "data" / "worker-runtime-libs.json").read_text())
    metadata, packages, copyrights = acquisition.frozen_manifest(manifest)
    trusted_hash = metadata[1].sha256
    trusted_size = metadata[1].size_bytes
    verified = (
        "Origin: Debian\nCodename: bookworm\nSHA256:\n"
        f" {trusted_hash} {trusted_size} {acquisition.INDEX_PATH}\n"
    )
    unsigned = (
        f"Origin: Debian\nCodename: bookworm\nSHA256:\n {'f' * 64} 1 {acquisition.INDEX_PATH}\n"
    )
    envelope = "-----BEGIN PGP SIGNED MESSAGE-----\n-----END PGP SIGNATURE-----\n"
    raw = unsigned + envelope if outside == "prefix" else envelope + unsigned
    acquisition.CACHE.mkdir(parents=True)
    (acquisition.CACHE / "bookworm.InRelease").write_text(raw)
    if replay:
        acquisition.MANIFEST.parent.mkdir()
        acquisition.MANIFEST.write_text(json.dumps(manifest))
    downloaded_indexes: list[tuple[int, str]] = []

    def fake_download(artifact: NamedArtifact) -> Path:
        if artifact.filename == "bookworm-amd64.Packages.xz":
            downloaded_indexes.append((artifact.size_bytes, artifact.sha256))
        return acquisition.CACHE / artifact.filename

    monkeypatch.setattr(acquisition, "download", fake_download)
    monkeypatch.setattr(acquisition, "verify_release", lambda: verified)
    monkeypatch.setattr(acquisition, "index_packages", lambda _: {})
    monkeypatch.setattr(acquisition, "dependency_closure", lambda _: packages)
    monkeypatch.setattr(acquisition, "license_inventory", lambda: json.dumps(copyrights))
    acquisition.main()
    result = json.loads(acquisition.MANIFEST.read_text())
    assert downloaded_indexes == [(trusted_size, trusted_hash)]
    assert result["metadata"][1]["sha256"] == trusted_hash
    assert result["metadata"][1]["size_bytes"] == trusted_size


def test_replay_rejects_incomplete_apt_closure_before_package_download(
    acquisition: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = json.loads((REPOSITORY / "data" / "worker-runtime-libs.json").read_text())
    metadata, packages, _ = acquisition.frozen_manifest(manifest)
    acquisition.MANIFEST.parent.mkdir()
    acquisition.MANIFEST.write_text(json.dumps(manifest))
    acquisition.CACHE.mkdir(parents=True)
    (acquisition.CACHE / "bookworm.InRelease").write_text("synthetic test release")
    downloads: list[str] = []

    def record_download(artifact: NamedArtifact) -> Path:
        filename = artifact.filename
        assert isinstance(filename, str)
        downloads.append(filename)
        return acquisition.CACHE / filename

    monkeypatch.setattr(acquisition, "download", record_download)
    monkeypatch.setattr(acquisition, "verify_release", lambda: "verified fixture")
    monkeypatch.setattr(
        acquisition, "release_index", lambda _: (metadata[1].size_bytes, metadata[1].sha256)
    )
    monkeypatch.setattr(acquisition, "index_packages", lambda _: {})
    monkeypatch.setattr(acquisition, "dependency_closure", lambda _: packages[:-1])
    with pytest.raises(ValueError, match="exact APT dependency closure"):
        acquisition.main()
    assert downloads == ["bookworm.InRelease", "bookworm-amd64.Packages.xz"]
    assert not (acquisition.CACHE / "SHA256SUMS").exists()
