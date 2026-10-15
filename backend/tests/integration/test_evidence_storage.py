"""Live atomic M1.4 source projection gates, with authored storage-only fixtures."""

import hashlib
import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import ConnectionInfo, Cursor
from pydantic import SecretStr

from backend.tests.evidence_fixtures import synthetic_artifact, synthetic_configuration
from regintel.auth.repository import seed_users
from regintel.auth.types import SeedAccount
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, connect_database
from regintel.evidence.projection import project_parse
from regintel.evidence.repository import EvidenceRepository, persist_parse
from regintel.ingestion.models import SourceBlob
from regintel.parsing.configuration import ParserRuntimeConfiguration
from regintel.parsing.models import ParseArtifact

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Context:
    job_id: str
    blob: SourceBlob
    artifact: ParseArtifact
    configuration: ParserRuntimeConfiguration


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def context(
    database: DatabaseSettings,
    *,
    config_hash: str | None = None,
    document_type: str = "RHP",
    published_on: str | None = None,
) -> Context:
    seed_users(
        database, (SeedAccount("admin", SecretStr("Synthetic evidence password!"), "admin"),)
    )
    configuration = synthetic_configuration()
    source_bytes = f"Synthetic storage fixture {uuid4()}".encode()
    sha = hashlib.sha256(source_bytes).hexdigest()
    blob = SourceBlob(
        id=str(uuid4()), sha256=sha, byte_size=len(source_bytes), storage_key=f"sha256/{sha}.pdf"
    )
    artifact = synthetic_artifact(configuration=configuration, blob=blob)
    job_id = str(uuid4())
    with connect_database(database) as connection, connection.transaction():
        actor = connection.execute(
            "SELECT id FROM regintel.users WHERE username='admin'"
        ).fetchone()
        assert actor is not None
        connection.execute(
            "INSERT INTO regintel.source_blobs(id,sha256,byte_size,storage_key) "
            "VALUES(%s,%s,%s,%s)",
            (blob.id, blob.sha256, blob.byte_size, blob.storage_key),
        )
        connection.execute(
            "INSERT INTO regintel.filings(id,company_name_raw) "
            "VALUES(%s,'Synthetic evidence issuer')",
            (artifact.filing_id,),
        )
        connection.execute(
            """INSERT INTO regintel.filing_versions
            (id,filing_id,source_blob_id,document_type,published_on) VALUES(%s,%s,%s,%s,%s)""",
            (artifact.filing_version_id, artifact.filing_id, blob.id, document_type, published_on),
        )
        connection.execute(
            """INSERT INTO regintel.filing_jobs
            (id,filing_version_id,source_blob_id,configuration_sha256,submitted_by)
            VALUES(%s,%s,%s,%s,%s)""",
            (
                job_id,
                artifact.filing_version_id,
                blob.id,
                config_hash or configuration.processing_configuration_sha256,
                actor[0],
            ),
        )
    with connect_database(database) as connection:
        connection.execute(
            "UPDATE regintel.filing_jobs SET state='RUNNING',attempts=1 WHERE id=%s", (job_id,)
        )
    return Context(job_id, blob, artifact, configuration)


def parsed(connection: DatabaseConnection, fixture: Context) -> None:
    connection.execute(
        "UPDATE regintel.filing_jobs SET state='PARSED',page_count=1,parse_version_id=%s "
        "WHERE id=%s",
        (fixture.artifact.id, fixture.job_id),
    )


def persist(connection: DatabaseConnection, fixture: Context) -> None:
    persist_parse(
        connection,
        job_id=fixture.job_id,
        artifact=fixture.artifact,
        configuration=fixture.configuration,
    )


def assert_no_tree(database: DatabaseSettings, job_id: str) -> None:
    with connect_database(database) as connection:
        for table in (
            "parse_versions",
            "pages",
            "blocks",
            "evidence",
            "evidence_boxes",
            "parse_artifacts",
        ):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)
        assert connection.execute(
            "SELECT state,attempts,parse_version_id FROM regintel.filing_jobs WHERE id=%s",
            (job_id,),
        ).fetchone() == ("RUNNING", 1, None)


def test_atomic_unicode_original_projection_and_authoritative_reader(auth_database):
    fixture = context(auth_database)
    with connect_database(auth_database) as connection, connection.transaction():
        persist(connection, fixture)
        parsed(connection, fixture)
    projection = project_parse(fixture.artifact, fixture.configuration)
    evidence_id = projection.evidence[0].id
    result = EvidenceRepository(auth_database).get_evidence(evidence_id)
    assert result is not None
    evidence, provenance, source_sha, processing_sha = result
    assert evidence == projection.evidence[0]
    assert evidence.span.quote == fixture.artifact.blocks[0].orig
    assert provenance == fixture.artifact.provenance
    assert source_sha == fixture.blob.sha256
    assert processing_sha == fixture.configuration.processing_configuration_sha256
    assert (
        EvidenceRepository(auth_database).get_source(fixture.artifact.filing_version_id)
        == fixture.blob
    )
    assert EvidenceRepository(auth_database).get_evidence(str(uuid4())) is None
    assert EvidenceRepository(auth_database).get_source(str(uuid4())) is None
    with connect_database(auth_database) as connection:
        for table, count in (
            ("pages", 1),
            ("blocks", 2),
            ("tables", 0),
            ("cells", 0),
            ("evidence", 1),
        ):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (
                count,
            )
        row = connection.execute(
            "SELECT artifact_bytes,configuration_bytes FROM regintel.parse_artifacts"
        ).fetchone()
        assert row == (projection.artifact_bytes, projection.configuration_bytes)


def test_sidecar_without_terminal_result_rolls_back_complete_tree(auth_database):
    fixture = context(auth_database)
    with connect_database(auth_database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            persist(connection, fixture)
    assert_no_tree(auth_database, fixture.job_id)


def test_mid_tree_failure_keeps_source_job_and_rolls_back_all_results(auth_database):
    fixture = context(auth_database)
    with connect_database(auth_database) as connection:
        with pytest.raises(RuntimeError, match="Synthetic interruption"), connection.transaction():
            persist(connection, fixture)
            raise RuntimeError("Synthetic interruption")
    assert_no_tree(auth_database, fixture.job_id)


@pytest.mark.parametrize(
    "command",
    [
        "UPDATE regintel.parse_artifacts SET artifact_bytes=decode('00','hex')",
        "DELETE FROM regintel.parse_artifacts",
        "TRUNCATE regintel.parse_artifacts CASCADE",
    ],
)
def test_sidecar_cannot_be_changed_removed_or_truncated(auth_database, command):
    fixture = context(auth_database)
    with connect_database(auth_database) as connection, connection.transaction():
        persist(connection, fixture)
        parsed(connection, fixture)
    with connect_database(auth_database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(command)
        assert connection.execute("SELECT count(*) FROM regintel.parse_artifacts").fetchone() == (
            1,
        )


class RedirectingConnection:
    """Alter authored SQL values to exercise the independent database gate."""

    def __init__(
        self,
        connection: DatabaseConnection,
        artifact_bytes: bytes,
        configuration_bytes: bytes,
        *,
        omit_sidecar: bool = False,
    ) -> None:
        self.connection = connection
        self.artifact_bytes = artifact_bytes
        self.configuration_bytes = configuration_bytes
        self.omit_sidecar = omit_sidecar

    @property
    def info(self) -> ConnectionInfo:
        return self.connection.info

    def execute(self, statement: str, parameters: tuple[object, ...]) -> Cursor[tuple[object, ...]]:
        values = list(parameters)
        if "INSERT INTO regintel.parse_versions" in statement:
            values[5] = hashlib.sha256(self.configuration_bytes).hexdigest()
            values[6] = hashlib.sha256(self.artifact_bytes).hexdigest()
        if "INSERT INTO regintel.parse_artifacts" in statement:
            if self.omit_sidecar:
                return self.connection.execute("SELECT 1")
            values[2], values[3] = self.artifact_bytes, self.configuration_bytes
        return self.connection.execute(statement, tuple(values))


def test_terminal_parse_without_sidecar_is_rejected_at_commit(auth_database):
    fixture = context(auth_database)
    projection = project_parse(fixture.artifact, fixture.configuration)
    with connect_database(auth_database) as connection:
        redirected = RedirectingConnection(
            connection, projection.artifact_bytes, projection.configuration_bytes, omit_sidecar=True
        )
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            persist(cast(DatabaseConnection, redirected), fixture)
            parsed(connection, fixture)
    assert_no_tree(auth_database, fixture.job_id)


@pytest.mark.parametrize(
    "mutation",
    [
        "source_sha",
        "filing_id",
        "coordinate_frame_null",
        "coordinate_frame_missing",
        "max_pages_null",
        "max_bytes_missing",
        "adapter_hash_null",
        "geometry_hash_missing",
        "sdk_hash_null",
        "source_limit_fraction",
        "source_limit_overflow",
        "backend_version",
        "processed_original",
        "page_geometry",
        "wrong_span_quote",
        "wrong_boxes",
    ],
)
def test_database_rejects_consistently_rehashed_bad_membership_or_projection(
    auth_database, mutation
):
    configuration = synthetic_configuration()
    configuration_value = configuration.model_dump(mode="json")
    if mutation == "coordinate_frame_null":
        configuration_value["coordinate_frame"] = None
    elif mutation == "coordinate_frame_missing":
        configuration_value.pop("coordinate_frame")
    elif mutation in {
        "max_pages_null",
        "max_bytes_missing",
        "source_limit_fraction",
        "source_limit_overflow",
    }:
        limits = configuration_value["source_limits"]
        assert isinstance(limits, dict)
        if mutation == "max_pages_null":
            limits["max_pages"] = None
        elif mutation == "max_bytes_missing":
            limits.pop("max_file_bytes")
        else:
            limits["max_pages"] = 1.5 if mutation == "source_limit_fraction" else 2001
    elif mutation in {"adapter_hash_null", "geometry_hash_missing", "sdk_hash_null"}:
        field = {
            "adapter_hash_null": "adapter_code_sha256",
            "geometry_hash_missing": "geometry_code_sha256",
            "sdk_hash_null": "sdk_configuration_sha256",
        }[mutation]
        if mutation == "geometry_hash_missing":
            configuration_value.pop(field)
        else:
            configuration_value[field] = None
    configuration_bytes = canonical(configuration_value)
    fixture = context(auth_database, config_hash=hashlib.sha256(configuration_bytes).hexdigest())
    artifact = fixture.artifact.model_dump(mode="json")
    provenance = artifact["provenance"]
    assert isinstance(provenance, dict)
    if mutation == "source_sha":
        artifact["source_sha256"] = "f" * 64
    elif mutation == "filing_id":
        artifact["filing_id"] = str(uuid4())
    elif mutation.startswith("coordinate_frame"):
        provenance["coordinate_frame"] = None
    elif mutation == "adapter_hash_null":
        provenance["adapter_code_sha256"] = None
    elif mutation == "sdk_hash_null":
        provenance["configuration_sha256"] = None
    elif mutation == "backend_version":
        provenance["backend_version"] = "wrong-version"
    elif mutation in {"processed_original", "wrong_span_quote", "wrong_boxes"}:
        blocks = artifact["blocks"]
        assert isinstance(blocks, list)
        block = blocks[0]
        if mutation == "processed_original":
            block["orig"] = block["text"]
        elif mutation == "wrong_span_quote":
            block["exact_spans"][0]["quote"] = "wrong quote"
        else:
            block["boxes"][0]["x0"] += 1
    elif mutation == "page_geometry":
        artifact["pages"][0]["geometry"]["rotation"] = 90
    artifact_bytes = canonical(artifact)
    with connect_database(auth_database) as connection:
        redirected = RedirectingConnection(connection, artifact_bytes, configuration_bytes)
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            persist(cast(DatabaseConnection, redirected), fixture)
            parsed(connection, fixture)
    assert_no_tree(auth_database, fixture.job_id)


def test_source_job_conflict_rejects_entire_result(auth_database):
    fixture, other = context(auth_database), context(auth_database)
    with connect_database(auth_database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            persist_parse(
                connection,
                job_id=other.job_id,
                artifact=fixture.artifact,
                configuration=fixture.configuration,
            )
    assert_no_tree(auth_database, fixture.job_id)


def test_sealed_legacy_tree_cannot_gain_a_sidecar_later(auth_database):
    fixture = context(auth_database)
    projection = project_parse(fixture.artifact, fixture.configuration)
    with connect_database(auth_database) as connection, connection.transaction():
        redirected = RedirectingConnection(
            connection, projection.artifact_bytes, projection.configuration_bytes, omit_sidecar=True
        )
        persist(cast(DatabaseConnection, redirected), fixture)
    with connect_database(auth_database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """INSERT INTO regintel.parse_artifacts
                (parse_version_id,job_id,artifact_bytes,configuration_bytes) VALUES(%s,%s,%s,%s)""",
                (
                    fixture.artifact.id,
                    fixture.job_id,
                    projection.artifact_bytes,
                    projection.configuration_bytes,
                ),
            )
        assert connection.execute("SELECT count(*) FROM regintel.parse_artifacts").fetchone() == (
            0,
        )


def test_legacy_source_verified_result_stays_immutable_and_unlinked(auth_database):
    fixture = context(auth_database)
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.filing_jobs SET state='SOURCE_VERIFIED',page_count=1 WHERE id=%s",
            (fixture.job_id,),
        )
        assert connection.execute(
            "SELECT state,page_count,parse_version_id FROM regintel.filing_jobs WHERE id=%s",
            (fixture.job_id,),
        ).fetchone() == ("SOURCE_VERIFIED", 1, None)
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE regintel.filing_jobs SET state='RUNNING',attempts=2 WHERE id=%s",
                (UUID(fixture.job_id),),
            )
