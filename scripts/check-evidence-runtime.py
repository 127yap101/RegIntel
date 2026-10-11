"""Controlled real M1.4 proof against an already-running native loopback API.

The only write to authoritative state is the authorized PDF upload API. Database
queries use read-only transactions. No service lifecycle, DDL, publication, paid
provider call or original-source rewrite occurs. Generated project credentials
are loaded through the established helpers and never printed.
"""

import argparse
import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx2
from psycopg.conninfo import conninfo_to_dict

from regintel.auth.config import load_seed_accounts
from regintel.contracts.models import TextEvidence
from regintel.db.config import DatabaseSettings, load_database_settings
from regintel.db.migrations import connect_database
from regintel.evidence.api import EvidenceEnvelope
from regintel.evidence.projection import MAX_ARTIFACT_BYTES, project_parse
from regintel.ingestion.jobs import FilingJob, FilingJobEnvelope, UploadMetadata
from regintel.parsing.configuration import (
    ParserRuntimeConfiguration,
    canonical_configuration_bytes,
    load_runtime_configuration,
    validate_artifact_provenance,
)
from regintel.parsing.models import ParseArtifact, canonical_artifact_bytes

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347"
SOURCE_SIZE = 196270
SOURCE_URL = "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2024/1725009610554.PDF"
SOURCE_PATH = "data/raw/premier-energies-addendum-rhp-sebi-20240826.pdf"
PROCESSING_SHA = "0674ad02f980861fcbc012832345a33fa4863146f00d995d4212dbbf98022f7f"
CIN = "U40106TG1995PLC019909"


class ProbeError(ValueError):
    """Fixed safe diagnostics omit credentials, response payloads and SQL text."""


@dataclass(frozen=True)
class ControlledSource:
    original: bytes
    metadata: UploadMetadata
    filing_id: str
    filing_version_id: str
    source_blob_id: str
    legacy_job_id: str


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeError(message)


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProbeError("Controlled metadata has an unexpected structure.")
    return cast(dict[str, object], value)


def identifier(value: object) -> str:
    if not isinstance(value, str):
        raise ProbeError("Controlled identity is invalid.")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ProbeError("Controlled identity is invalid.") from None
    expect(str(parsed) == value and parsed.version == 4, "Controlled identity is invalid.")
    return value


def api_base(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.username is None
            and parsed.password is None
            and parsed.port is not None
            and 1 <= parsed.port <= 65535
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and not any(character.isspace() or ord(character) < 32 for character in value)
        )
    except ValueError:
        valid = False
    expect(valid, "An explicit HTTP 127.0.0.1 API URL and port are required.")
    return value.rstrip("/")


def plain_path(path: Path, *, directory: bool = False) -> None:
    expect(path.is_absolute() and ".." not in path.parts, "Controlled path is invalid.")
    expect(path == ROOT or ROOT in path.parents, "Controlled path is outside the project.")
    for part in (path, *path.parents):
        expect(not part.is_symlink() and not part.is_junction(), "Controlled path is linked.")
    expect(path.resolve() == path, "Controlled path is not canonical.")
    if directory:
        expect(path.is_dir(), "Controlled artifact directory is unavailable.")


def read_regular(path: Path, maximum: int) -> bytes:
    plain_path(path)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        expect(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
            "Controlled file is not a bounded regular file.",
        )
        contents = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        expect(
            len(contents) == before.st_size
            and len(contents) <= maximum
            and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            "Controlled file changed while being read.",
        )
    return contents


def controlled_source() -> ControlledSource:
    manifest = mapping(json.loads(read_regular(ROOT / "data/manifest.json", 1024 * 1024)))
    documents = manifest.get("documents")
    expect(isinstance(documents, list), "Controlled source manifest is unavailable.")
    records = [mapping(value) for value in cast(list[object], documents)]
    selected = [record for record in records if record.get("sha256") == SOURCE_SHA]
    expect(len(selected) == 1, "Controlled source manifest membership is ambiguous.")
    record = selected[0]
    expect(
        record.get("byte_size") == SOURCE_SIZE
        and record.get("page_count") == 3
        and record.get("local_path") == SOURCE_PATH
        and record.get("cin_raw") == CIN,
        "Controlled source manifest identity changed.",
    )
    metadata = UploadMetadata.model_validate(
        {
            "company_name_raw": record.get("company_name_raw"),
            "document_type": record.get("document_type"),
            "source_url": record.get("source_url"),
            "published_on": record.get("publication_date"),
            "declared_parent_filing_version_id": None,
        }
    )
    expect(
        metadata
        == UploadMetadata(
            company_name_raw="Premier Energies Limited",
            document_type="ADDENDUM",
            source_url=SOURCE_URL,
        )
        and record.get("parent_filing_id") is None,
        "Controlled upload metadata changed.",
    )
    original = read_regular(ROOT / SOURCE_PATH, 64 * 1024 * 1024)
    expect(
        len(original) == SOURCE_SIZE and hashlib.sha256(original).hexdigest() == SOURCE_SHA,
        "Controlled original source hash or size changed.",
    )
    ingestion = mapping(mapping(record.get("verification")).get("ingestion"))
    return ControlledSource(
        original,
        metadata,
        identifier(record.get("filing_id")),
        identifier(record.get("filing_version_id")),
        identifier(record.get("source_blob_id")),
        identifier(ingestion.get("job_id")),
    )


def checked_database() -> DatabaseSettings:
    plain_path(ROOT / ".env")
    settings = load_database_settings(ROOT / ".env")
    parameters = conninfo_to_dict(settings.database_url.get_secret_value())
    expect(
        parameters.get("host") in {"127.0.0.1", "localhost", "::1"}
        and parameters.get("hostaddr") in {None, "127.0.0.1", "::1"}
        and parameters.get("port") == "5432"
        and parameters.get("dbname") == "regintel",
        "The proof requires the existing loopback project database.",
    )
    return settings


def legacy_snapshot(database: DatabaseSettings, source: ControlledSource) -> tuple[object, ...]:
    with connect_database(database) as connection, connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = 5000")
        row = connection.execute(
            """SELECT id,filing_version_id,source_blob_id,configuration_sha256,
            state,attempts,page_count,failure_code,submitted_by,created_at,updated_at,
            parse_version_id FROM regintel.filing_jobs WHERE id=%s""",
            (UUID(source.legacy_job_id),),
        ).fetchone()
        migration = connection.execute(
            "SELECT version FROM regintel_meta.schema_migrations WHERE version=5"
        ).fetchone()
        membership = connection.execute(
            """SELECT v.filing_id,v.source_blob_id,s.sha256,s.byte_size,k.metadata_sha256
            FROM regintel.filing_versions v JOIN regintel.source_blobs s ON s.id=v.source_blob_id
            JOIN regintel.filing_ingestion_keys k ON k.filing_version_id=v.id WHERE v.id=%s""",
            (UUID(source.filing_version_id),),
        ).fetchone()
    expect(migration is not None, "M1.4 migration is not applied; no upload was attempted.")
    expect(
        row is not None
        and str(row[1]) == source.filing_version_id
        and str(row[2]) == source.source_blob_id
        and row[4] == "SOURCE_VERIFIED"
        and row[6] == 3
        and row[7] is None
        and row[11] is None,
        "The legacy source-verification job is not preserved.",
    )
    expect(
        membership is not None
        and str(membership[0]) == source.filing_id
        and str(membership[1]) == source.source_blob_id
        and membership[2] == SOURCE_SHA
        and membership[3] == SOURCE_SIZE
        and membership[4] == source.metadata.sha256,
        "Controlled authoritative source membership or metadata changed.",
    )
    return cast(tuple[object, ...], row)


def authorized(client: httpx2.Client) -> dict[str, dict[str, str]]:
    plain_path(ROOT / ".env.auth")
    accounts = load_seed_accounts(ROOT / ".env.auth")
    expect({account.role for account in accounts} == {"admin", "learner"}, "Seed roles changed.")
    headers: dict[str, dict[str, str]] = {}
    for account in accounts:
        response = client.post(
            "/v1/auth/token",
            data={
                "grant_type": "password",
                "username": account.username,
                "password": account.password.get_secret_value(),
            },
            timeout=10,
        )
        expect(response.status_code == 200, "Generated account authentication failed.")
        token = mapping(response.json()).get("access_token")
        expect(
            isinstance(token, str) and 0 < len(token) <= 8192, "Authentication token is invalid."
        )
        headers[account.role] = {"Authorization": f"Bearer {token}"}
    return headers


def wait_for_job(
    client: httpx2.Client, headers: dict[str, str], job_id: str, seconds: int
) -> tuple[FilingJob, int]:
    deadline = time.monotonic() + seconds
    polls = 0
    while (remaining := deadline - time.monotonic()) > 0:
        response = client.get(
            f"/v1/filing-jobs/{job_id}", headers=headers, timeout=min(5, remaining)
        )
        polls += 1
        expect(response.status_code == 200, "Authoritative job status is unavailable.")
        job = FilingJobEnvelope.model_validate_json(response.text).data
        if job.state == "PARSED":
            expect(job.parse_version_id is not None, "Parsed job has no immutable result identity.")
            return job, polls
        expect(job.state != "FAILED", "Controlled parsing returned a terminal failure.")
        expect(job.state in {"QUEUED", "RUNNING"}, "Selected parser job has an unexpected state.")
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise ProbeError("Controlled parser did not finish inside the bounded wait.")


def persisted_result(
    database: DatabaseSettings, job: FilingJob, configuration: ParserRuntimeConfiguration
) -> tuple[ParseArtifact, str, bytes]:
    with connect_database(database) as connection, connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = 5000")
        row = connection.execute(
            """SELECT a.artifact_bytes,a.configuration_bytes,r.artifact_sha256,
            r.configuration_sha256 FROM regintel.parse_artifacts a
            JOIN regintel.parse_versions r ON r.id=a.parse_version_id
            JOIN regintel.filing_jobs j ON j.id=a.job_id AND j.state='PARSED'
            AND j.parse_version_id=r.id WHERE j.id=%s AND r.id=%s""",
            (UUID(job.id), UUID(cast(str, job.parse_version_id))),
        ).fetchone()
        evidence = connection.execute(
            """SELECT e.id FROM regintel.evidence e JOIN regintel.pages p ON p.id=e.page_id
            WHERE e.parse_version_id=%s AND e.kind='text' AND p.page_index=0
            AND strpos(e.quote,%s)>0 ORDER BY e.id LIMIT 1""",
            (UUID(cast(str, job.parse_version_id)), CIN),
        ).fetchone()
    expect(row is not None and evidence is not None, "Persisted CIN evidence is unavailable.")
    retained = cast(tuple[object, ...], row)
    expect(
        isinstance(retained[0], (bytes, memoryview))
        and isinstance(retained[1], (bytes, memoryview)),
        "Persisted artifact sidecar is unavailable.",
    )
    contents = bytes(cast(bytes | memoryview, retained[0]))
    descriptor = bytes(cast(bytes | memoryview, retained[1]))
    expect(0 < len(contents) <= MAX_ARTIFACT_BYTES, "Persisted artifact exceeds its byte limit.")
    expect(
        hashlib.sha256(contents).hexdigest() == retained[2]
        and retained[3] == PROCESSING_SHA
        and descriptor == canonical_configuration_bytes(configuration),
        "Persisted parser identity or sidecar digest differs.",
    )
    artifact = ParseArtifact.model_validate_json(contents)
    expect(canonical_artifact_bytes(artifact) == contents, "Persisted artifact is not canonical.")
    validate_artifact_provenance(configuration, provenance=artifact.provenance)
    expect(
        artifact.id == job.parse_version_id
        and artifact.filing_version_id == job.filing_version_id
        and artifact.source_blob_id == job.source_blob_id
        and artifact.source_sha256 == SOURCE_SHA,
        "Persisted artifact has conflicting source or result membership.",
    )
    return artifact, str(cast(tuple[object, ...], evidence)[0]), contents


def exact_evidence(
    client: httpx2.Client,
    headers: dict[str, str],
    evidence_id: str,
    artifact: ParseArtifact,
    configuration: ParserRuntimeConfiguration,
) -> TextEvidence:
    response = client.get(f"/v1/evidence/{evidence_id}", headers=headers, timeout=10)
    expect(response.status_code == 200, "Protected exact evidence is unavailable.")
    envelope = EvidenceEnvelope.model_validate_json(response.text)
    item = envelope.data.record
    projection = project_parse(artifact, configuration)
    matching = [record for record in projection.evidence if record.id == item.id]
    expect(
        len(matching) == 1
        and matching[0] == item
        and CIN in item.span.quote
        and item.source.page_index == 0
        and item.source.parse_version_id == artifact.id
        and item.source.filing_id == artifact.filing_id
        and item.source.filing_version_id == artifact.filing_version_id
        and envelope.data.provenance == artifact.provenance
        and envelope.data.source_sha256 == SOURCE_SHA
        and envelope.data.processing_configuration_sha256 == PROCESSING_SHA
        and envelope.meta.versions.parse_version_id == artifact.id
        and envelope.meta.versions.filing_version_id == artifact.filing_version_id
        and envelope.meta.versions.corpus_version_id is None,
        "Protected evidence does not match its exact retained source and parser identity.",
    )
    blocks = [block for block in artifact.blocks if block.id == item.span.block_id]
    expect(
        len(blocks) == 1
        and blocks[0].orig is not None
        and blocks[0].orig[item.span.start : item.span.end] == item.span.quote,
        "Persisted evidence offsets do not round-trip exact original Unicode.",
    )
    expect(response.headers.get("cache-control") == "no-store", "Evidence caching policy changed.")
    return item


def verify_sources(
    client: httpx2.Client, source: ControlledSource, auth: dict[str, dict[str, str]]
) -> tuple[bytes, dict[str, object]]:
    path = f"/v1/filing-versions/{source.filing_version_id}/source.pdf"
    etag = f'"{SOURCE_SHA}"'
    for headers, status in (({}, 401), (auth["learner"], 403)):
        denied = client.get(path, headers={**headers, "If-None-Match": etag}, timeout=10)
        expect(
            denied.status_code == status
            and "etag" not in denied.headers
            and denied.headers.get("cache-control") == "no-store",
            "Source authorization did not precede its conditional representation.",
        )
    full = client.get(path, headers=auth["admin"], timeout=15)
    expect(
        full.status_code == 200
        and full.content == source.original
        and len(full.content) == SOURCE_SIZE
        and hashlib.sha256(full.content).hexdigest() == SOURCE_SHA
        and full.headers.get("content-type") == "application/pdf"
        and full.headers.get("content-length") == str(SOURCE_SIZE)
        and full.headers.get("etag") == etag
        and full.headers.get("accept-ranges") == "bytes"
        and full.headers.get("cache-control") == "no-store",
        "Authenticated whole-source bytes, digest or representation headers differ.",
    )
    for requested, start, end in (
        ("bytes=0-31", 0, 31),
        ("bytes=-32", SOURCE_SIZE - 32, SOURCE_SIZE - 1),
    ):
        selected = client.get(
            path, headers={**auth["admin"], "Range": requested, "If-Range": etag}, timeout=10
        )
        expect(
            selected.status_code == 206
            and selected.content == source.original[start : end + 1]
            and selected.headers.get("content-range") == f"bytes {start}-{end}/{SOURCE_SIZE}"
            and selected.headers.get("content-length") == str(end - start + 1)
            and selected.headers.get("etag") == etag
            and selected.headers.get("cache-control") == "no-store",
            "Authenticated range bytes or inclusive headers differ.",
        )
    unsatisfiable = client.get(
        path, headers={**auth["admin"], "Range": f"bytes={SOURCE_SIZE}-"}, timeout=10
    )
    expect(
        unsatisfiable.status_code == 416
        and unsatisfiable.headers.get("content-range") == f"bytes */{SOURCE_SIZE}"
        and unsatisfiable.headers.get("etag") == etag,
        "Unsatisfiable source range did not return its exact size.",
    )
    head = client.head(path, headers={**auth["admin"], "Range": "bytes=0-31"}, timeout=10)
    expect(
        head.status_code == 200
        and not head.content
        and head.headers.get("content-length") == str(SOURCE_SIZE)
        and head.headers.get("etag") == etag
        and "content-range" not in head.headers,
        "HEAD did not preserve full-source metadata while ignoring Range.",
    )
    unchanged = client.get(path, headers={**auth["admin"], "If-None-Match": etag}, timeout=10)
    expect(
        unchanged.status_code == 304
        and not unchanged.content
        and unchanged.headers.get("etag") == etag
        and unchanged.headers.get("cache-control") == "no-store",
        "Authenticated verified conditional source did not return 304.",
    )
    return full.content, {
        "sha256": SOURCE_SHA,
        "byte_size": SOURCE_SIZE,
        "etag": etag,
        "content_type": full.headers.get("content-type"),
        "full_get": 200,
        "closed_range": 206,
        "suffix_range": 206,
        "unsatisfiable_range": 416,
        "head": 200,
        "if_none_match": 304,
        "unauthenticated_matching_etag": 401,
        "learner_matching_etag": 403,
        "source_http_checks": 8,
        "original_bytes_changed": False,
    }


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def save_proof(
    *,
    artifact_bytes: bytes,
    evidence: TextEvidence,
    original: bytes,
    source_report: dict[str, object],
    report: dict[str, object],
) -> Path:
    directory = ROOT / ".cache" / f"evidence-runtime-{uuid4().hex}"
    plain_path(directory.parent, directory=True)
    directory.mkdir(mode=0o700)
    plain_path(directory, directory=True)
    for name, contents in (
        ("parse-artifact.json", artifact_bytes),
        ("evidence.json", canonical_json(evidence.model_dump(mode="json"))),
        ("source.pdf", original),
        ("source-verification.json", canonical_json(source_report)),
        ("runtime-report.json", canonical_json(report)),
    ):
        with (directory / name).open("xb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
    return directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base", required=True, help="Existing http://127.0.0.1:PORT native API"
    )
    parser.add_argument(
        "--wait-seconds", type=int, default=180, help="Job wait bound, 1-180 seconds"
    )
    arguments = parser.parse_args()
    base = api_base(arguments.api_base)
    expect(1 <= arguments.wait_seconds <= 180, "Job wait must be between 1 and 180 seconds.")
    configuration = load_runtime_configuration(ROOT / "data/parser-runtime-config.json")
    expect(
        configuration.processing_configuration_sha256 == PROCESSING_SHA,
        "The selected parser processing identity changed.",
    )
    source = controlled_source()
    database = checked_database()
    legacy = legacy_snapshot(database, source)
    started = time.monotonic()
    with httpx2.Client(
        base_url=base, timeout=10, trust_env=False, follow_redirects=False
    ) as client:
        expect(
            client.get("/health/live", timeout=5).status_code == 200, "Native API is unavailable."
        )
        auth = authorized(client)
        parameters = {
            "company_name_raw": source.metadata.company_name_raw,
            "document_type": source.metadata.document_type,
            "source_url": source.metadata.source_url,
        }
        uploaded = client.post(
            "/v1/filings",
            params=parameters,
            headers={**auth["admin"], "Content-Type": "application/pdf"},
            content=source.original,
            timeout=15,
        )
        expect(
            uploaded.status_code == 202, "Controlled source upload did not return a durable job."
        )
        submitted = FilingJobEnvelope.model_validate_json(uploaded.text).data
        expect(
            submitted.filing_version_id == source.filing_version_id
            and submitted.source_blob_id == source.source_blob_id
            and submitted.source_sha256 == SOURCE_SHA
            and submitted.configuration_sha256 == PROCESSING_SHA
            and submitted.id != source.legacy_job_id,
            "Selected parser job did not reuse its immutable controlled source membership.",
        )
        print(f"Controlled evidence proof waiting for parser job {submitted.id}.", flush=True)
        parsed, polls = wait_for_job(client, auth["admin"], submitted.id, arguments.wait_seconds)
        expect(
            parsed.configuration_sha256 == PROCESSING_SHA
            and parsed.source_sha256 == SOURCE_SHA
            and parsed.filing_version_id == source.filing_version_id
            and parsed.source_blob_id == source.source_blob_id
            and parsed.page_count == 3,
            "Completed parser job has conflicting source identity or page count.",
        )
        artifact, evidence_id, artifact_bytes = persisted_result(database, parsed, configuration)
        evidence = exact_evidence(client, auth["admin"], evidence_id, artifact, configuration)
        original, source_report = verify_sources(client, source, auth)
    expect(legacy_snapshot(database, source) == legacy, "Runtime proof changed the legacy job.")
    expect(
        read_regular(ROOT / SOURCE_PATH, SOURCE_SIZE) == source.original, "Original source changed."
    )
    report: dict[str, object] = {
        "status": "passed",
        "purpose": "controlled M1.4 engineering proof; not research gold",
        "job_id": parsed.id,
        "parse_version_id": parsed.parse_version_id,
        "filing_version_id": parsed.filing_version_id,
        "source_blob_id": parsed.source_blob_id,
        "source_sha256": SOURCE_SHA,
        "processing_configuration_sha256": PROCESSING_SHA,
        "sdk_configuration_sha256": artifact.provenance.configuration_sha256,
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "evidence_id": evidence.id,
        "evidence_page_index": evidence.source.page_index,
        "page_count": len(artifact.pages),
        "exact_evidence_count": len(project_parse(artifact, configuration).evidence),
        "job_attempts": parsed.attempts,
        "job_status_polls": polls,
        "runtime_seconds": time.monotonic() - started,
        "legacy_job_preserved": True,
        "original_source_preserved": True,
        "accepted_or_published": False,
        "source_http_checks": source_report["source_http_checks"],
    }
    directory = save_proof(
        artifact_bytes=artifact_bytes,
        evidence=evidence,
        original=original,
        source_report=source_report,
        report=report,
    )
    print(json.dumps({**report, "proof_directory": str(directory)}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeError as error:
        raise SystemExit(f"Evidence runtime proof failed: {error}") from None
    except Exception:
        raise SystemExit(
            "Evidence runtime proof failed; diagnostics and credentials omitted."
        ) from None
