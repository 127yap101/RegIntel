"""Real HTTP contracts, current-account authorization and immutable PDF byte policy."""

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from regintel.auth.config import AuthSettings
from regintel.auth.errors import AuthUnavailable
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import User
from regintel.config import Settings
from regintel.contracts.models import (
    EvidenceSource,
    PageGeometry,
    PdfRectangle,
    TextEvidence,
    TextSpan,
)
from regintel.evidence.api import EvidenceEnvelope, EvidenceService
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.models import SourceBlob
from regintel.ingestion.storage import SourceStorage
from regintel.main import create_app
from regintel.parsing.models import PackageVersion, ParseProvenance, package_manifest_sha256

ID1 = "00000000-0000-4000-8000-000000000001"
ID2 = "00000000-0000-4000-8000-000000000002"
ID3 = "00000000-0000-4000-8000-000000000003"
ID4 = "00000000-0000-4000-8000-000000000004"
ID5 = "00000000-0000-4000-8000-000000000005"
ID6 = "00000000-0000-4000-8000-000000000006"
SOURCE_PATH = f"/v1/filing-versions/{ID2}/source.pdf"
EVIDENCE_PATH = f"/v1/evidence/{ID5}"
DATA = b"%PDF-1.7\n" + bytes(range(256)) * 16 + b"\n%%EOF"


class Users:
    def __init__(self, user: User) -> None:
        self.user: User | None = user
        self.unavailable = False

    def get_by_username(self, username: str) -> User | None:
        return self.user if self.user and self.user.username == username else None

    def get_by_id(self, user_id: UUID) -> User | None:
        if self.unavailable:
            raise AuthUnavailable("private auth database diagnostic")
        return self.user if self.user and self.user.id == user_id else None


class EvidenceMemory:
    def __init__(self, blob: SourceBlob, record: TextEvidence, provenance: ParseProvenance) -> None:
        self.blob: SourceBlob | None = blob
        self.result: tuple[TextEvidence, ParseProvenance, str, str] | None = (
            record,
            provenance,
            blob.sha256,
            "d" * 64,
        )
        self.calls: list[str] = []
        self.unavailable = False

    def get_source(self, filing_version_id: str) -> SourceBlob | None:
        self.calls.append("source")
        if self.unavailable:
            raise psycopg.OperationalError("private SQL connection diagnostic")
        return self.blob

    def get_evidence(
        self, evidence_id: str
    ) -> tuple[TextEvidence, ParseProvenance, str, str] | None:
        self.calls.append("evidence")
        if self.unavailable:
            raise psycopg.OperationalError("private SQL connection diagnostic")
        return self.result


class CountingStorage(SourceStorage):
    def __init__(self, settings: IngestionSettings) -> None:
        super().__init__(settings)
        self.reads = 0

    def read(self, blob: SourceBlob) -> BinaryIO:
        self.reads += 1
        return super().read(blob)


@dataclass
class Boundary:
    client: TestClient
    users: Users
    user: User
    token: str
    storage: CountingStorage
    repository: EvidenceMemory

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @property
    def etag(self) -> str:
        return '"' + hashlib.sha256(DATA).hexdigest() + '"'


@pytest.fixture
def boundary(tmp_path: Path) -> Iterator[Boundary]:
    user = User(UUID(ID1), "admin", SecretStr("synthetic unused hash"), "admin", True, 1)
    users = Users(user)
    auth_settings = AuthSettings(jwt_secret=SecretStr("ab" * 32))
    auth = AuthService(users, auth_settings)
    storage = CountingStorage(
        IngestionSettings(
            source_root=tmp_path / "sources",
            broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0"),
        )
    )
    sha = hashlib.sha256(DATA).hexdigest()
    blob = SourceBlob(id=ID6, sha256=sha, byte_size=len(DATA), storage_key=f"sha256/{sha}.pdf")
    (storage.root / blob.storage_key).write_bytes(DATA)
    media = PdfRectangle(x0=-10.0, y0=-20.0, x1=602.0, y1=772.0)
    quote = "₹100.00 α 🧪 e\u0301"
    record = TextEvidence(
        id=ID5,
        kind="text",
        source=EvidenceSource(
            filing_id=ID1,
            filing_version_id=ID2,
            parse_version_id=ID3,
            page_id=ID4,
            page_index=0,
        ),
        page_geometry=PageGeometry(
            width=612.0,
            height=792.0,
            media_box=media,
            crop_box=media,
            rotation=90,
            coordinate_space="UNROTATED_PDF_POINTS",
            origin="BOTTOM_LEFT",
        ),
        boxes=(PdfRectangle(x0=0.0, y0=10.0, x1=150.0, y1=30.0),),
        span=TextSpan(block_id=ID6, start=0, end=len(quote), quote=quote),
    )
    packages = (PackageVersion(name="synthetic-parser", version="1.0"),)
    provenance = ParseProvenance(
        adapter_name="synthetic",
        adapter_version="1.0",
        adapter_code_sha256="a" * 64,
        backend_name="synthetic",
        backend_version="1.0",
        backend_code_sha256="b" * 64,
        coordinate_frame="CROP_ROTATED_TOP_LEFT",
        packages=packages,
        package_manifest_sha256=package_manifest_sha256(packages),
        configuration_sha256="c" * 64,
        model_manifest_sha256="e" * 64,
    )
    repository = EvidenceMemory(blob, record, provenance)
    service = EvidenceService(repository, storage)
    with TestClient(
        create_app(Settings(environment="test"), auth_service=auth, evidence_service=service)
    ) as client:
        yield Boundary(client, users, user, issue_token(user, auth_settings), storage, repository)


def test_exact_evidence_contract_retains_unicode_and_unpublished_versions(
    boundary: Boundary,
) -> None:
    response = boundary.client.get(EVIDENCE_PATH, headers=boundary.headers)
    assert response.status_code == 200
    envelope = EvidenceEnvelope.model_validate_json(response.text)
    assert boundary.repository.result is not None
    assert envelope.data.record == boundary.repository.result[0]
    assert envelope.data.record.span.quote == "₹100.00 α 🧪 e\u0301"
    assert envelope.data.provenance == boundary.repository.result[1]
    assert envelope.data.source_sha256 == hashlib.sha256(DATA).hexdigest()
    assert envelope.data.processing_configuration_sha256 == "d" * 64
    assert envelope.meta.versions.filing_version_id == ID2
    assert envelope.meta.versions.parse_version_id == ID3
    assert envelope.meta.versions.corpus_version_id is None
    assert response.headers["cache-control"] == "no-store"
    assert boundary.storage.reads == 0


def test_full_pdf_response_is_original_authenticated_snapshot(boundary: Boundary) -> None:
    response = boundary.client.get(SOURCE_PATH, headers=boundary.headers)
    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == str(len(DATA))
    assert response.headers["etag"] == boundary.etag
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "no-store"
    assert "content-range" not in response.headers
    assert boundary.storage.reads == 1


@pytest.mark.parametrize(
    ("range_value", "start", "end"),
    [
        ("bytes=0-4", 0, 4),
        ("bytes=3-", 3, len(DATA) - 1),
        ("bytes=-5", len(DATA) - 5, len(DATA) - 1),
        ("bytes=0-999999", 0, len(DATA) - 1),
    ],
)
def test_range_bytes_and_inclusive_lengths(
    boundary: Boundary, range_value: str, start: int, end: int
) -> None:
    response = boundary.client.get(SOURCE_PATH, headers={**boundary.headers, "Range": range_value})
    assert response.status_code == 206
    assert response.content == DATA[start : end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/{len(DATA)}"
    assert response.headers["content-length"] == str(end - start + 1)
    assert response.headers["etag"] == boundary.etag
    assert boundary.storage.reads == 1


@pytest.mark.parametrize("value", ["bytes=999999-", "bytes=-0", "bytes=5-4"])
def test_unsatisfiable_range_retains_source_headers(boundary: Boundary, value: str) -> None:
    response = boundary.client.get(SOURCE_PATH, headers={**boundary.headers, "Range": value})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(DATA)}"
    assert response.headers["etag"] == boundary.etag
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("value", ["bytes=0-4,10-15", "items=0-4"])
def test_valid_unsupported_range_uses_full_response(boundary: Boundary, value: str) -> None:
    response = boundary.client.get(SOURCE_PATH, headers={**boundary.headers, "Range": value})
    assert response.status_code == 200
    assert response.content == DATA


@pytest.mark.parametrize("condition", ["matching", "weak", "other", "date"])
def test_if_range_strong_tag_policy(boundary: Boundary, condition: str) -> None:
    value = {
        "matching": boundary.etag,
        "weak": "W/" + boundary.etag,
        "other": '"other"',
        "date": "Mon, 01 Jan 2024 00:00:00 GMT",
    }[condition]
    response = boundary.client.get(
        SOURCE_PATH, headers={**boundary.headers, "Range": "bytes=0-4", "If-Range": value}
    )
    assert response.status_code == (206 if condition == "matching" else 200)
    assert response.content == (DATA[:5] if condition == "matching" else DATA)


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("value", ["strong", "weak", "star"])
def test_none_match_requires_verified_source_before_304(
    boundary: Boundary, method: str, value: str
) -> None:
    tag = {"strong": boundary.etag, "weak": "W/" + boundary.etag, "star": "*"}[value]
    response = boundary.client.request(
        method, SOURCE_PATH, headers={**boundary.headers, "If-None-Match": tag}
    )
    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == boundary.etag
    assert response.headers["cache-control"] == "no-store"
    assert boundary.repository.calls == ["source"]
    assert boundary.storage.reads == 1


def test_head_ignores_range_and_keeps_full_length(boundary: Boundary) -> None:
    response = boundary.client.head(
        SOURCE_PATH, headers={**boundary.headers, "Range": "malformed" + "9" * 3000}
    )
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == str(len(DATA))
    assert "content-range" not in response.headers


def test_revoked_head_has_no_lookup_or_read_even_with_matching_tag(boundary: Boundary) -> None:
    boundary.users.user = replace(boundary.user, auth_version=2)
    response = boundary.client.head(
        SOURCE_PATH, headers={**boundary.headers, "If-None-Match": boundary.etag}
    )
    assert response.status_code == 401
    assert response.content == b""
    assert boundary.repository.calls == []
    assert boundary.storage.reads == 0


def test_pdf_browser_preflight_and_exposed_range_headers(boundary: Boundary) -> None:
    origin = "http://127.0.0.1:5173"
    preflight = boundary.client.options(
        SOURCE_PATH,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "HEAD",
            "Access-Control-Request-Headers": "Authorization, Range, If-Range, If-None-Match",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert preflight.headers["cache-control"] == "no-store"
    response = boundary.client.get(
        SOURCE_PATH, headers={**boundary.headers, "Origin": origin, "Range": "bytes=0-4"}
    )
    assert response.status_code == 206
    exposed = {
        value.strip().lower()
        for value in response.headers["access-control-expose-headers"].split(",")
    }
    assert {"etag", "content-range", "accept-ranges", "content-length"} <= exposed


@pytest.mark.parametrize("path", [SOURCE_PATH, EVIDENCE_PATH])
@pytest.mark.parametrize(
    "state", ["missing", "invalid", "learner", "revoked", "inactive", "deleted", "outage"]
)
def test_authorization_precedes_all_lookup_read_and_conditional_results(
    boundary: Boundary, path: str, state: str
) -> None:
    headers = {**boundary.headers, "If-None-Match": boundary.etag, "Range": "bytes=0-4"}
    expected = 401
    if state == "missing":
        del headers["Authorization"]
    elif state == "invalid":
        headers["Authorization"] = "Bearer invalid"
    elif state == "learner":
        boundary.users.user = replace(boundary.user, role="learner")
        expected = 403
    elif state == "revoked":
        boundary.users.user = replace(boundary.user, auth_version=2)
    elif state == "inactive":
        boundary.users.user = replace(boundary.user, is_active=False)
    elif state == "deleted":
        boundary.users.user = None
    elif state == "outage":
        boundary.users.unavailable = True
        expected = 503
    response = boundary.client.get(path, headers=headers)
    assert response.status_code == expected
    assert boundary.repository.calls == []
    assert boundary.storage.reads == 0
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text


@pytest.mark.parametrize("tamper", ["same-size", "different-size", "missing"])
def test_integrity_failure_precedes_matching_conditional(boundary: Boundary, tamper: str) -> None:
    assert boundary.repository.blob is not None
    path = boundary.storage.root / boundary.repository.blob.storage_key
    if tamper == "missing":
        path.unlink()
    else:
        path.write_bytes(b"x" * (len(DATA) if tamper == "same-size" else 3))
    response = boundary.client.get(
        SOURCE_PATH, headers={**boundary.headers, "If-None-Match": boundary.etag}
    )
    assert response.status_code == 503
    assert "etag" not in response.headers
    assert b"x" * 100 not in response.content


@pytest.mark.parametrize("path", [SOURCE_PATH, EVIDENCE_PATH])
def test_missing_or_unavailable_repository_is_sanitized(boundary: Boundary, path: str) -> None:
    boundary.repository.blob = None
    boundary.repository.result = None
    assert boundary.client.get(path, headers=boundary.headers).status_code == 404
    boundary.repository.unavailable = True
    failed = boundary.client.get(path, headers=boundary.headers)
    assert failed.status_code == 503
    assert "private" not in failed.text


@pytest.mark.parametrize("header", ["Range", "If-Range", "If-None-Match"])
def test_oversized_conditionals_and_duplicate_headers_are_bounded(
    boundary: Boundary, header: str
) -> None:
    failed = boundary.client.get(SOURCE_PATH, headers={**boundary.headers, header: "9" * 2049})
    assert failed.status_code == 400
    failed = boundary.client.get(
        SOURCE_PATH,
        headers=[*boundary.headers.items(), (header, "bytes=0-4"), (header, "bytes=5-9")],
    )
    assert failed.status_code == 400
