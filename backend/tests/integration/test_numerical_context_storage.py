"""Read-only joint-context inspection; authored engineering fixtures are not gold data."""

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg import sql
from pydantic import SecretStr

from backend.tests.evidence_fixtures import synthetic_artifact
from backend.tests.integration.test_evidence_storage import context, parsed, persist
from backend.tests.test_numerical_context import CIN, ISSUER, authored
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.types import SeedAccount, User
from regintel.candidates.repository import CandidateRepository
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import connect_database
from regintel.entities.models import ApprovedIdentifier, EntityRegistration, EvidenceAnchor
from regintel.entities.repository import EntityRepository
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.jobs import UploadMetadata
from regintel.ingestion.repository import JobRepository
from regintel.ingestion.storage import SourceStorage
from regintel.numerical.context_models import NumericalContextDraft, WordPhrase
from regintel.numerical.context_repository import NumericalContextRepository
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
)
from regintel.parsing.configuration import ParserRuntimeConfiguration
from regintel.validation.repository import ValidationRepository

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class InspectionContext:
    database: DatabaseSettings
    source: NumericalRepository
    repository: NumericalContextRepository
    draft: NumericalContextDraft
    user: User
    learner: User
    source_path: Path


def snapshot(database: DatabaseSettings) -> dict[str, str]:
    """Hash every authority/preparation table, including payloads and audit columns."""
    result: dict[str, str] = {}
    with connect_database(database) as connection:
        names = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='regintel' ORDER BY tablename"
        ).fetchall()
        for (name,) in names:
            row = connection.execute(
                sql.SQL(
                    "SELECT coalesce(string_agg(row_to_json(t)::text, E'\\n' "
                    "ORDER BY row_to_json(t)::text),'') FROM regintel.{} t"
                ).format(sql.Identifier(name))
            ).fetchone()
            assert row is not None
            result[name] = hashlib.sha256(row[0].encode("utf-8")).hexdigest()
    return result


def register_issuer(database: DatabaseSettings, user: User, identity: str) -> None:
    """Use persisted M1 exact evidence, never the pure test's invented evidence anchors."""
    fixture = context(database)
    text = f"{ISSUER} CORPORATE IDENTITY NUMBER: {CIN}"
    artifact = synthetic_artifact(
        configuration=fixture.configuration,
        blob=fixture.blob,
        parse_id=fixture.artifact.id,
        filing_id=fixture.artifact.filing_id,
        filing_version_id=fixture.artifact.filing_version_id,
        original=text,
    )
    fixture = replace(fixture, artifact=artifact)
    with connect_database(database) as connection, connection.transaction():
        persist(connection, fixture)
        parsed(connection, fixture)
    repository = EntityRepository(database)
    evidence, _ = repository.evidence_for_parse(artifact.id)

    def anchor(quote: str) -> EvidenceAnchor:
        start = evidence[0].span.start + text.index(quote)
        return EvidenceAnchor(
            evidence_id=evidence[0].id, start=start, end=start + len(quote), quote=quote
        )

    repository.register(
        EntityRegistration(
            id=identity,
            kind="COMPANY",
            legal_name=ISSUER,
            legal_name_support=anchor(ISSUER),
            identifiers=(ApprovedIdentifier(kind="CIN", value=CIN, support=anchor(CIN)),),
            review_note="Authored engineering identity; no real filing or human-review claim.",
        ),
        user,
    )


def prepare_inspection(
    auth_database: DatabaseSettings,
    tmp_path: Path,
    *,
    approvals: str = "all",
    metadata: UploadMetadata | None = None,
) -> InspectionContext:
    case = authored(tmp_path)
    seed_users(
        auth_database,
        (
            SeedAccount("admin", SecretStr("Synthetic evidence password!"), "admin"),
            SeedAccount("learner", SecretStr("Authored context fixture password!"), "learner"),
        ),
    )
    accounts = PostgreSQLAuthRepository(auth_database)
    user, learner = accounts.get_by_username("admin"), accounts.get_by_username("learner")
    assert user is not None and learner is not None
    settings = IngestionSettings(
        source_root=tmp_path / "owned-sources",
        broker_url=SecretStr("redis://:authored@127.0.0.1:6379/0"),
    )
    storage = SourceStorage(settings)
    stage = storage.stage()
    stage.write(case.source.read_bytes())
    stored = stage.finish()
    job = JobRepository(auth_database).submit(
        stored,
        metadata or UploadMetadata(company_name_raw=ISSUER, document_type="RHP"),
        settings.configuration_sha256,
        user.id,
        user.auth_version,
    )
    configuration = ParserRuntimeConfiguration.model_validate_json(
        (ROOT / "data/parser-runtime-config.json").read_bytes()
    ).model_copy(update={"sdk_configuration_sha256": case.input.sdk_configuration_sha256})
    source = NumericalRepository(auth_database, storage, configuration)
    page = source.save(
        job.filing_version_id,
        json.dumps(
            case.raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8"),
        2,
        user,
    )

    def mapped(phrase: WordPhrase) -> WordPhrase:
        return phrase.model_copy(
            update={
                "words": tuple(
                    ref.model_copy(update={"capture_id": page.id}) for ref in phrase.words
                )
            }
        )

    original = case.input.draft
    draft = original.model_copy(
        update={
            "filing_version_id": job.filing_version_id,
            **{
                role: getattr(original, role).model_copy(
                    update={"phrase": mapped(getattr(original, role).phrase)}
                )
                for role in ("value", "row_label", "period_header")
            },
            **{
                role: mapped(getattr(original, role))
                for role in ("issuer_header", "table_scope", "unit_header")
            },
            "currency_definitions": tuple(mapped(p) for p in original.currency_definitions),
            "fiscal_definitions": tuple(mapped(p) for p in original.fiscal_definitions),
        }
    )
    if approvals != "no_issuer":
        register_issuer(auth_database, user, draft.subject_entity_id)
    assert case.input.metric is not None and case.input.policy is not None
    if approvals != "no_metric":
        CandidateRepository(auth_database).register_metric(case.input.metric, user)
    if approvals not in {"no_metric", "no_policy"}:
        ValidationRepository(auth_database).register_policy(case.input.policy, user)
    return InspectionContext(
        auth_database,
        source,
        NumericalContextRepository(source),
        draft,
        user,
        learner,
        storage.root / stored.blob.storage_key,
    )


@pytest.fixture
def inspection(
    auth_database: DatabaseSettings, tmp_path: Path, request: pytest.FixtureRequest
) -> InspectionContext:
    return prepare_inspection(auth_database, tmp_path, approvals=getattr(request, "param", "all"))


def test_inspection_uses_current_approved_snapshots_and_never_writes(inspection: InspectionContext):
    before = snapshot(inspection.database)
    result = inspection.repository.inspect(inspection.draft, inspection.user)
    assert result.state == "SUPPORTED_PROPOSAL"
    assert result.quantity is not None and str(result.quantity.normalized_value) == "2500.20"
    assert not result.acceptance_eligible and not result.mandatory_m1_validation_complete
    assert inspection.repository.inspect(inspection.draft, inspection.user) == result
    assert snapshot(inspection.database) == before
    with connect_database(inspection.database) as connection:
        for table in ("acceptance_audits", "fact_observations", "corpus_versions"):
            assert connection.execute(
                sql.SQL("SELECT count(*) FROM regintel.{}").format(sql.Identifier(table))
            ).fetchone() == (0,)


@pytest.mark.parametrize("inspection", ["no_issuer", "no_metric", "no_policy"], indirect=True)
def test_missing_approvals_remain_unavailable_for_acceptance(inspection: InspectionContext):
    before = snapshot(inspection.database)
    result = inspection.repository.inspect(inspection.draft, inspection.user)
    assert result.state == "REVIEW_REQUIRED" and not result.acceptance_eligible
    assert any(c.state == "REVIEW" for c in result.checks if c.code in {"ISSUER", "METRIC"})
    assert snapshot(inspection.database) == before


@pytest.mark.parametrize("change", ["learner", "forged_role", "stale", "inactive", "demoted"])
def test_current_administrator_is_required_without_writes(
    inspection: InspectionContext, change: str
):
    user = inspection.user
    if change in {"learner", "forged_role"}:
        user = inspection.learner
        if change == "forged_role":
            user = replace(user, role="admin")
    else:
        command = {
            "stale": "auth_version=auth_version+1",
            "inactive": "is_active=false",
            "demoted": "role='learner'",
        }[change]
        with connect_database(inspection.database) as connection:
            connection.execute(f"UPDATE regintel.users SET {command} WHERE id=%s", (user.id,))
    before = snapshot(inspection.database)
    with pytest.raises(NumericalAuthorizationError):
        inspection.repository.inspect(inspection.draft, user)
    assert snapshot(inspection.database) == before


@pytest.mark.parametrize("change", ["modified", "missing"])
def test_original_source_is_reverified_for_current_inspection(
    inspection: InspectionContext, change: str
):
    if change == "modified":
        inspection.source_path.write_bytes(inspection.source_path.read_bytes() + b"modified")
    else:
        inspection.source_path.unlink()
    before = snapshot(inspection.database)
    with pytest.raises(NumericalSourceError):
        inspection.repository.inspect(inspection.draft, inspection.user)
    assert snapshot(inspection.database) == before


def test_unstored_reference_cannot_be_inspected(inspection: InspectionContext):
    phrase = inspection.draft.issuer_header
    foreign = str(uuid4())
    draft = inspection.draft.model_copy(
        update={
            "issuer_header": phrase.model_copy(
                update={
                    "words": tuple(
                        ref.model_copy(update={"capture_id": foreign}) for ref in phrase.words
                    )
                }
            )
        }
    )
    before = snapshot(inspection.database)
    with pytest.raises(NumericalNotFound):
        inspection.repository.inspect(draft, inspection.user)
    assert snapshot(inspection.database) == before
