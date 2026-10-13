"""Acquire authenticated, frozen Debian runtime libraries; never install on the host."""

from __future__ import annotations

import hashlib
import json
import lzma
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from http.client import HTTPMessage
from pathlib import Path, PurePosixPath
from typing import IO, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "worker-debs"
MANIFEST = ROOT / "data" / "worker-runtime-libs.json"
# The Debian-listed mirrors.kernel.org endpoint redirects to this verified CDN.
MIRROR = "https://mirrors.edge.kernel.org/debian"
BASE_IMAGE = (
    "python:3.12.15-slim-bookworm@sha256:"
    "34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258"
)
INDEX_PATH = "main/binary-amd64/Packages.xz"
ROOT_PACKAGES = ("libgl1", "libglib2.0-0", "libxcb1")
PACKAGE_NAME = re.compile(r"[a-z0-9][a-z0-9+.-]*\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
FILENAME = re.compile(r"[A-Za-z0-9+_.~-]+\Z")
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_INDEX_BYTES = 80 * 1024 * 1024


@dataclass(frozen=True)
class Artifact:
    filename: str
    url: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    architecture: str
    artifact: Artifact


def checked_path(path: Path) -> None:
    if not path.is_absolute() or not path.is_relative_to(ROOT) or ".." in path.parts:
        raise ValueError("Path is outside the project workspace")
    for component in [*reversed(path.parents), path]:
        if component.is_symlink() or component.is_junction():
            raise ValueError("Project acquisition path is a link or junction")
    if path.resolve() != path:
        raise ValueError("Project acquisition path resolves elsewhere")


def ensure_directory(path: Path) -> None:
    checked_path(path)
    for component in [*reversed(path.parents), path]:
        if not component.is_relative_to(ROOT):
            continue
        checked_path(component)
        try:
            component.mkdir()
        except FileExistsError:
            if not component.is_dir():
                raise ValueError("Project acquisition directory is not a directory") from None
        checked_path(component)


def checked_file(path: Path) -> None:
    checked_path(path)
    if not path.is_file():
        raise ValueError("Project acquisition artifact is not a regular file")


def publish(temporary: Path, target: Path) -> None:
    checked_file(temporary)
    checked_path(target)
    try:
        os.link(temporary, target)
    except FileExistsError:
        checked_file(target)
        if target.stat().st_size != temporary.stat().st_size or sha256(target) != sha256(temporary):
            raise ValueError("Concurrent acquisition published different bytes") from None
    checked_file(target)


def publish_bytes(target: Path, data: bytes) -> None:
    ensure_directory(target.parent)
    checked_path(target)
    if target.exists():
        checked_file(target)
        if target.stat().st_size != len(data) or target.read_bytes() != data:
            raise ValueError("Existing immutable acquisition record differs")
        return
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.part")
    try:
        checked_path(temporary)
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        publish(temporary, target)
    finally:
        checked_path(temporary)
        temporary.unlink(missing_ok=True)


def allowed_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        return (
            not any(ord(character) <= 32 or ord(character) == 127 for character in url)
            and parsed.scheme == "https"
            and parsed.hostname == "mirrors.edge.kernel.org"
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and parsed.path.startswith("/debian/")
            and urllib.parse.unquote(parsed.path) == parsed.path
            and not any(component in {".", ".."} for component in parsed.path.split("/"))
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if not allowed_url(newurl):
            raise urllib.error.URLError("Debian redirect leaves the approved HTTPS mirror")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def https_client() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        RestrictedRedirect(),
    )


def sha256(path: Path) -> str:
    checked_file(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256")
    return digest.hexdigest()


def download(artifact: Artifact) -> Path:
    if (
        not FILENAME.fullmatch(artifact.filename)
        or not allowed_url(artifact.url)
        or type(artifact.size_bytes) is not int
        or not 0 < artifact.size_bytes <= MAX_ARTIFACT_BYTES
        or not SHA256.fullmatch(artifact.sha256)
    ):
        raise ValueError("Invalid bounded Debian artifact specification")
    target = CACHE / artifact.filename
    ensure_directory(CACHE)
    checked_path(target)
    if target.exists():
        checked_file(target)
        if target.stat().st_size != artifact.size_bytes:
            raise ValueError(f"Existing artifact differs: {artifact.filename}")
        if sha256(target) != artifact.sha256:
            raise ValueError(f"Existing artifact hash differs: {artifact.filename}")
        return target
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.part")
    try:
        with https_client().open(artifact.url, timeout=60) as response:
            if not allowed_url(response.url):
                raise ValueError("Unexpected Debian artifact redirect")
            digest = hashlib.sha256()
            count = 0
            checked_path(temporary)
            with temporary.open("xb") as stream:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > artifact.size_bytes:
                        raise ValueError("Debian artifact exceeds authenticated size")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if count != artifact.size_bytes:
                raise ValueError("Debian artifact size differs")
            if digest.hexdigest() != artifact.sha256:
                raise ValueError("Debian artifact hash differs")
        publish(temporary, target)
        return target
    finally:
        checked_path(temporary)
        temporary.unlink(missing_ok=True)


def docker(arguments: list[str], *, code: str | None = None) -> str:
    executable = (
        Path(os.environ["LOCALAPPDATA"]) / "Programs/DockerDesktop/resources/bin/docker.exe"
        if os.name == "nt"
        else Path(shutil.which("docker") or "/usr/bin/docker")
    )
    command = [
        str(executable),
        "--config",
        str(ROOT / ".cache" / "docker"),
    ]
    if os.name == "nt":
        command.extend(["--host", "npipe:////./pipe/dockerDesktopLinuxEngine"])
    command.extend(
        [
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=160m",
            "--mount",
            f"type=bind,source={CACHE},target=/input,readonly",
        ]
    )
    if code is not None:
        command.append("-i")
    command.extend(["--entrypoint", arguments[0], BASE_IMAGE, *arguments[1:]])
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        command,
        input=code,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        creationflags=creationflags,
    )
    if result.returncode:
        raise RuntimeError(f"Offline Debian verification failed: {result.stderr[-4000:]}")
    return result.stdout


def verify_release() -> str:
    # gpgv may tolerate bytes outside the signed envelope. Only its successfully
    # verified plaintext can supply repository identity, index hashes or sizes.
    return docker(
        [
            "gpgv",
            "--output",
            "-",
            "--keyring",
            "/usr/share/keyrings/debian-archive-keyring.gpg",
            "/input/bookworm.InRelease",
        ]
    )


def release_index(release: str) -> tuple[int, str]:
    if "-----BEGIN PGP" in release or "-----END PGP" in release:
        raise ValueError("Expected signature-verified release plaintext")
    if not all(field in release.splitlines() for field in ("Origin: Debian", "Codename: bookworm")):
        raise ValueError("Signed archive identity is not Debian Bookworm")
    in_sha256 = False
    for line in release.splitlines():
        if line == "SHA256:":
            in_sha256 = True
        elif in_sha256 and line and not line.startswith(" "):
            break
        elif in_sha256:
            fields = line.split()
            if len(fields) == 3 and fields[2] == INDEX_PATH:
                return int(fields[1]), fields[0]
    raise ValueError("Signed Debian release omits the expected package index")


def bounded_index(raw: bytes) -> bytes:
    decoder = lzma.LZMADecompressor(memlimit=128 * 1024 * 1024)
    content = decoder.decompress(raw, max_length=MAX_INDEX_BYTES + 1)
    if len(content) > MAX_INDEX_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError("Package index exceeds the configured parse bound")
    return content


def index_packages(path: Path) -> dict[tuple[str, str], Package]:
    checked_file(path)
    raw = bounded_index(path.read_bytes())
    result: dict[tuple[str, str], Package] = {}
    for paragraph in raw.decode("utf-8").split("\n\n"):
        fields = {}
        for line in paragraph.splitlines():
            if line and not line.startswith(" ") and ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value
        if not fields or fields.get("Architecture") not in {"amd64", "all"}:
            continue
        name = fields["Package"]
        filename = PurePosixPath(fields["Filename"])
        if (
            not PACKAGE_NAME.fullmatch(name)
            or filename.is_absolute()
            or ".." in filename.parts
            or not str(filename).startswith("pool/")
        ):
            raise ValueError("Invalid authenticated package identity or path")
        identity = (name, fields["Version"])
        if identity in result:
            raise ValueError("Duplicate package identity in the frozen index")
        result[identity] = Package(
            name,
            fields["Version"],
            fields["Architecture"],
            Artifact(
                filename.name,
                f"{MIRROR}/{filename}",
                int(fields["Size"]),
                fields["SHA256"],
            ),
        )
    return result


def dependency_closure(packages: dict[tuple[str, str], Package]) -> list[Package]:
    # APT applies Debian's version/dependency semantics to the authenticated index.
    # Its exact selected versions become immutable manifest pins below.
    roots = list(ROOT_PACKAGES)
    code = """
import lzma
from pathlib import Path
import subprocess
import sys
target = Path('/tmp/apt/lists')
target.mkdir(parents=True)
(target / 'mirrors.edge.kernel.org_debian_dists_bookworm_InRelease').write_bytes(
    Path('/input/bookworm.InRelease').read_bytes())
decoder = lzma.LZMADecompressor(memlimit=128 * 1024 * 1024)
content = decoder.decompress(Path('/input/bookworm-amd64.Packages.xz').read_bytes(),
    max_length=80 * 1024 * 1024 + 1)
if len(content) > 80 * 1024 * 1024 or not decoder.eof or decoder.unused_data:
    raise ValueError('Package index exceeds configured read bound')
(target / 'mirrors.edge.kernel.org_debian_dists_bookworm_main_binary-amd64_Packages').write_bytes(
    content)
Path('/tmp/apt/sources.list').write_text(
    'deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] '
    'https://mirrors.edge.kernel.org/debian bookworm main\\n')
command = ['apt-get', '--simulate', '--no-install-recommends',
    '-o', 'Dir::State::lists=/tmp/apt/lists',
    '-o', 'Dir::Etc::sourcelist=/tmp/apt/sources.list',
    '-o', 'Dir::Etc::sourceparts=-', 'install', *sys.argv[1:]]
process = subprocess.run(command, capture_output=True, text=True)
print(process.stdout)
if process.returncode:
    print(process.stderr, file=sys.stderr)
    raise SystemExit(process.returncode)
"""
    output = docker(["python", "-", *roots], code=code)
    selected = []
    for line in output.splitlines():
        match = re.match(r"Inst ([\w+.-]+)(?: \[[^]]+\])? \((\S+)", line)
        if match:
            name, version = match.groups()
            package = packages[(name, version)]
            selected.append(package)
    if not set(ROOT_PACKAGES).issubset(package.name for package in selected):
        raise ValueError("Incomplete Debian dependency closure")
    return sorted(selected, key=lambda package: package.name)


def mapping(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Frozen Debian record schema differs")
    return cast(dict[str, object], value)


def text_field(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Frozen Debian string field is invalid")
    return value


def records(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Frozen Debian sequence field is invalid")
    return cast(list[object], value)


def positive_integer(value: object, maximum: int) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError("Frozen Debian integer field is invalid")
    return value


def artifact_record(value: object) -> Artifact:
    record = mapping(value, {"filename", "url", "size_bytes", "sha256"})
    artifact = Artifact(
        text_field(record["filename"]),
        text_field(record["url"]),
        positive_integer(record["size_bytes"], MAX_ARTIFACT_BYTES),
        text_field(record["sha256"]),
    )
    if (
        not FILENAME.fullmatch(artifact.filename)
        or not allowed_url(artifact.url)
        or not SHA256.fullmatch(artifact.sha256)
    ):
        raise ValueError("Frozen Debian artifact identity is invalid")
    return artifact


def frozen_manifest(value: object) -> tuple[list[Artifact], list[Package], dict[str, object]]:
    record = mapping(
        value,
        {
            "schema_version",
            "base_image",
            "mirror",
            "architecture",
            "root_packages",
            "signature_verification",
            "metadata",
            "packages",
        },
    )
    expected = {
        "schema_version": "worker-runtime-libs-v1",
        "base_image": BASE_IMAGE,
        "mirror": MIRROR,
        "architecture": "amd64",
        "root_packages": list(ROOT_PACKAGES),
        "signature_verification": "gpgv with digest-pinned base Debian archive keyring",
    }
    if any(record[key] != required for key, required in expected.items()):
        raise ValueError("Frozen Debian acquisition identity differs")
    metadata = [artifact_record(item) for item in records(record["metadata"])]
    if [(artifact.filename, artifact.url) for artifact in metadata] != [
        ("bookworm.InRelease", f"{MIRROR}/dists/bookworm/InRelease"),
        ("bookworm-amd64.Packages.xz", f"{MIRROR}/dists/bookworm/{INDEX_PATH}"),
    ]:
        raise ValueError("Frozen Debian metadata identity differs")
    packages = []
    copyrights: dict[str, object] = {}
    for item in records(record["packages"]):
        package_record = mapping(item, {"name", "version", "architecture", "artifact", "copyright"})
        package = Package(
            text_field(package_record["name"]),
            text_field(package_record["version"]),
            text_field(package_record["architecture"]),
            artifact_record(package_record["artifact"]),
        )
        if (
            not PACKAGE_NAME.fullmatch(package.name)
            or package.architecture not in {"amd64", "all"}
            or package.name in copyrights
        ):
            raise ValueError("Frozen Debian package identity is invalid or duplicated")
        copyright_record = mapping(
            package_record["copyright"], {"copyright_bytes", "copyright_sha256", "license_labels"}
        )
        positive_integer(copyright_record["copyright_bytes"], 2 * 1024 * 1024)
        if not SHA256.fullmatch(text_field(copyright_record["copyright_sha256"])):
            raise ValueError("Frozen Debian copyright hash is invalid")
        labels = [text_field(label) for label in records(copyright_record["license_labels"])]
        if labels != sorted(set(labels)):
            raise ValueError("Frozen Debian license labels are duplicated or unordered")
        copyrights[package.name] = copyright_record
        packages.append(package)
    if packages != sorted(packages, key=lambda package: package.name) or len(packages) > 100:
        raise ValueError("Frozen Debian package list is unordered or exceeds its bound")
    filenames = [artifact.filename for artifact in metadata]
    filenames.extend(package.artifact.filename for package in packages)
    if len(filenames) != len(set(filenames)):
        raise ValueError("Duplicate frozen Debian artifact filename")
    return metadata, packages, copyrights


def seal_checksums(metadata: list[Artifact], packages: list[Package]) -> None:
    checksums = [f"{artifact.sha256}  {artifact.filename}" for artifact in metadata]
    checksums.extend(
        f"{package.artifact.sha256}  {package.artifact.filename}" for package in packages
    )
    publish_bytes(CACHE / "SHA256SUMS", ("\n".join(checksums) + "\n").encode("utf-8"))


def license_inventory() -> str:
    return docker(
        ["python", "-"],
        code="""
import hashlib
import json
from pathlib import Path
import posixpath
import re
import subprocess
import tarfile
result = {}
documents = {}
links = {}
package_names = []
for archive in sorted(Path('/input').glob('*.deb')):
    package = subprocess.check_output(
        ['dpkg-deb', '-f', str(archive), 'Package'], text=True).strip()
    package_names.append(package)
    process = subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(archive)], stdout=subprocess.PIPE)
    with tarfile.open(fileobj=process.stdout, mode='r|') as stream:
        for member in stream:
            name = member.name.removeprefix('./')
            if not name.startswith('usr/share/doc/') or not name.endswith('/copyright'):
                continue
            if member.issym():
                links[name] = posixpath.normpath(
                    posixpath.join(posixpath.dirname(name), member.linkname))
            elif member.isfile():
                if member.size > 2 * 1024 * 1024:
                    raise ValueError('Debian copyright exceeds configured read bound')
                documents[name] = stream.extractfile(member).read()
    if process.wait(timeout=30):
        raise RuntimeError('Debian package copyright extraction failed')
for package in package_names:
    path = 'usr/share/doc/' + package + '/copyright'
    seen = set()
    while path in links:
        if path in seen or not path.startswith('usr/share/doc/'):
            raise ValueError('Invalid Debian copyright link')
        seen.add(path)
        path = links[path]
    raw = documents[path]
    result[package] = {
        'copyright_bytes': len(raw), 'copyright_sha256': hashlib.sha256(raw).hexdigest(),
        'license_labels': sorted(set(re.findall(r'^License: (.+)$', raw.decode('utf-8'), re.M)))}
print(json.dumps(result, sort_keys=True))
""",
    )


def main() -> None:
    ensure_directory(CACHE)
    checked_path(MANIFEST)
    if MANIFEST.exists():
        checked_file(MANIFEST)
        if MANIFEST.stat().st_size > 512 * 1024:
            raise ValueError("Frozen Debian manifest exceeds its configured read bound")
        metadata, packages, copyrights = frozen_manifest(
            json.loads(MANIFEST.read_text(encoding="utf-8"))
        )
        for artifact in metadata:
            download(artifact)
        verified_release = verify_release()
        size, digest = release_index(verified_release)
        if (metadata[1].size_bytes, metadata[1].sha256) != (size, digest):
            raise ValueError("Frozen package index differs from the signed release")
        indexed = index_packages(CACHE / "bookworm-amd64.Packages.xz")
        if dependency_closure(indexed) != packages:
            raise ValueError("Frozen packages differ from the exact APT dependency closure")
        for package in packages:
            download(package.artifact)
        if json.loads(license_inventory()) != copyrights:
            raise ValueError("Frozen package copyrights differ from actual package files")
        seal_checksums(metadata, packages)
        print(json.dumps({"frozen_packages_verified": len(packages)}))
        return
    release_url = f"{MIRROR}/dists/bookworm/InRelease"
    # Bootstrap bytes remain untrusted until gpgv verifies the base-image archive keys.
    release_path = CACHE / "bookworm.InRelease"
    checked_path(release_path)
    if release_path.exists():
        checked_file(release_path)
        if release_path.stat().st_size > 256 * 1024:
            raise ValueError("Debian signed release exceeds its configured read bound")
        raw = release_path.read_bytes()
    else:
        with https_client().open(release_url, timeout=60) as response:
            raw = response.read(256 * 1024 + 1)
            if not allowed_url(response.url) or len(raw) > 256 * 1024:
                raise ValueError("Unexpected or oversized Debian signed release")
        publish_bytes(release_path, raw)
    release = Artifact("bookworm.InRelease", release_url, len(raw), hashlib.sha256(raw).hexdigest())
    verified_release = verify_release()
    size, digest = release_index(verified_release)
    index = Artifact(
        "bookworm-amd64.Packages.xz", f"{MIRROR}/dists/bookworm/{INDEX_PATH}", size, digest
    )
    index_path = download(index)
    packages = dependency_closure(index_packages(index_path))
    for package in packages:
        download(package.artifact)
    licenses = json.loads(license_inventory())
    seal_checksums([release, index], packages)
    manifest = {
        "schema_version": "worker-runtime-libs-v1",
        "base_image": BASE_IMAGE,
        "mirror": MIRROR,
        "architecture": "amd64",
        "root_packages": list(ROOT_PACKAGES),
        "signature_verification": "gpgv with digest-pinned base Debian archive keyring",
        "metadata": [asdict(release), asdict(index)],
        "packages": [
            dict(asdict(package), copyright=licenses[package.name]) for package in packages
        ],
    }
    frozen_manifest(manifest)
    publish_bytes(MANIFEST, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps({"acquired_packages": len(packages), "manifest": str(MANIFEST)}))


if __name__ == "__main__":
    main()
