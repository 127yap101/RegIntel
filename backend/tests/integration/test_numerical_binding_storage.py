"""Read-only links to persisted M1 engineering evidence in an owned disposable database."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import psycopg
import pytest

from backend.tests.integration.test_numerical_context_storage import InspectionContext, snapshot
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.numerical_binding_fixtures import BindingFixture, complete_artifact
from regintel.db.migrations import connect_database
from regintel.evidence.repository import EvidenceRepository, persist_parse
from regintel.numerical.context_storage import NumericalContextStorage
from regintel.numerical.evidence_binding_repository import NumericalEvidenceBindingRepository
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class StoredBindingFixture:
    source: InspectionContext
    case: BindingFixture
    repository: NumericalEvidenceBindingRepository


def sealed(source: InspectionContext, case: BindingFixture) -> None:
    job_id = uuid4()
    with connect_database(source.database) as connection, connection.transaction():
        connection.execute(
            "INSERT INTO regintel.filing_jobs(id,filing_version_id,source_blob_id,"
            "configuration_sha256,submitted_by) VALUES(%s,%s,%s,%s,%s)",
            (
                job_id,
                UUID(case.artifact.filing_version_id),
                UUID(case.artifact.source_blob_id),
                case.configuration.processing_configuration_sha256,
                source.user.id,
            ),
        )
        connection.execute(
            "UPDATE regintel.filing_jobs SET state='RUNNING',attempts=1 WHERE id=%s", (job_id,)
        )
        persist_parse(
            connection, job_id=str(job_id), artifact=case.artifact, configuration=case.configuration
        )
        connection.execute(
            "UPDATE regintel.filing_jobs SET state='PARSED',page_count=%s,parse_version_id=%s "
            "WHERE id=%s",
            (len(case.artifact.pages), UUID(case.artifact.id), job_id),
        )


@pytest.fixture
def binding(inspection: InspectionContext) -> StoredBindingFixture:
    record = NumericalContextStorage(inspection.source).save(inspection.draft, inspection.user)
    with connect_database(inspection.database) as connection:
        owner = connection.execute(
            "SELECT filing_id FROM regintel.filing_versions WHERE id=%s",
            (UUID(record.filing_version_id),),
        ).fetchone()
    assert owner is not None
    case = complete_artifact(record, filing_id=str(owner[0]))
    sealed(inspection, case)
    return StoredBindingFixture(
        inspection, case, NumericalEvidenceBindingRepository(inspection.source)
    )


def test_exact_binding_uses_actual_sealed_evidence_and_changes_no_tables(
    binding: StoredBindingFixture,
):
    fixture, case, repository = binding.source, binding.case, binding.repository
    before = snapshot(fixture.database)
    result = repository.bind(case.record.id, case.artifact.id, fixture.user)
    assert repository.bind(case.record.id, case.artifact.id, fixture.user) == result
    value = result.phrases[0].words[0].evidence
    actual = EvidenceRepository(fixture.database).get_evidence(value.id)
    assert actual is not None and actual[0] == value
    assert value.span.quote == "2,500.20" and value.source.page_index == 1
    assert not result.acceptance_eligible and not result.mandatory_m1_validation_complete
    assert snapshot(fixture.database) == before


def test_concurrent_read_only_bindings_replay_exactly(binding: StoredBindingFixture):
    fixture, case, repository = binding.source, binding.case, binding.repository
    before = snapshot(fixture.database)
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [
            workers.submit(repository.bind, case.record.id, case.artifact.id, fixture.user)
            for _ in range(2)
        ]
        results = [call.result(timeout=40) for call in calls]
    assert results[0] == results[1] and snapshot(fixture.database) == before


@pytest.mark.parametrize("inspection", ["no_policy"], indirect=True)
def test_exact_links_do_not_replace_missing_financial_approval(binding: StoredBindingFixture):
    fixture, case = binding.source, binding.case
    assert (
        case.record.inspection.state == "REVIEW_REQUIRED"
        and case.record.source_input.policy is None
    )
    before = snapshot(fixture.database)
    result = binding.repository.bind(case.record.id, case.artifact.id, fixture.user)
    assert not result.acceptance_eligible and result.review_required
    assert snapshot(fixture.database) == before


def test_selected_parse_is_explicit_and_history_never_switches_by_timestamp(
    binding: StoredBindingFixture,
):
    fixture, case, repository = binding.source, binding.case, binding.repository
    old = repository.bind(case.record.id, case.artifact.id, fixture.user)
    later = complete_artifact(case.record, filing_id=case.artifact.filing_id)
    # Existing jobs deduplicate a filing/configuration pair. Use a distinct, explicit
    # authored source-limit configuration for the second historical parse.
    later = replace(
        later,
        configuration=later.configuration.model_copy(
            update={
                "source_limits": later.configuration.source_limits.model_copy(
                    update={"max_pages": 1999}
                )
            }
        ),
    )
    sealed(fixture, later)
    before = snapshot(fixture.database)
    new = repository.bind(case.record.id, later.artifact.id, fixture.user)
    assert new.parse_version_id != old.parse_version_id and new.id != old.id
    assert new.phrases[0].words[0].evidence.id != old.phrases[0].words[0].evidence.id
    assert repository.bind(case.record.id, case.artifact.id, fixture.user) == old
    assert snapshot(fixture.database) == before


def test_another_sealed_filings_words_cannot_support_this_context(binding: StoredBindingFixture):
    fixture, case = binding.source, binding.case
    with connect_database(fixture.database) as connection:
        other = connection.execute(
            "SELECT id FROM regintel.parse_versions WHERE id<>%s LIMIT 1", (UUID(case.artifact.id),)
        ).fetchone()
    assert other is not None
    before = snapshot(fixture.database)
    with pytest.raises(NumericalSourceError):
        binding.repository.bind(case.record.id, str(other[0]), fixture.user)
    assert snapshot(fixture.database) == before


@pytest.mark.parametrize("missing", ["record", "parse"])
def test_missing_or_unparsed_sources_fail_closed(binding: StoredBindingFixture, missing: str):
    fixture, case = binding.source, binding.case
    before = snapshot(fixture.database)
    with pytest.raises(NumericalNotFound):
        binding.repository.bind(
            str(uuid4()) if missing == "record" else case.record.id,
            str(uuid4()) if missing == "parse" else case.artifact.id,
            fixture.user,
        )
    assert snapshot(fixture.database) == before


@pytest.mark.parametrize("change", ["learner", "forged_role", "stale", "inactive", "demoted"])
def test_binding_rechecks_current_admin_without_writes(binding: StoredBindingFixture, change: str):
    fixture, case = binding.source, binding.case
    user = fixture.user
    if change == "learner":
        user = fixture.learner
    elif change == "forged_role":
        user = replace(fixture.learner, role="admin")
    elif change == "stale":
        user = replace(user, auth_version=user.auth_version + 1)
    else:
        with connect_database(fixture.database) as connection:
            if change == "inactive":
                connection.execute(
                    "UPDATE regintel.users SET is_active=false WHERE id=%s", (user.id,)
                )
            else:
                connection.execute(
                    "UPDATE regintel.users SET role='learner' WHERE id=%s", (user.id,)
                )
    before = snapshot(fixture.database)
    with pytest.raises(NumericalAuthorizationError):
        binding.repository.bind(case.record.id, case.artifact.id, user)
    assert snapshot(fixture.database) == before


@pytest.mark.parametrize("change", ["modified", "missing"])
def test_binding_reverifies_physical_original(binding: StoredBindingFixture, change: str):
    fixture, case = binding.source, binding.case
    if change == "modified":
        fixture.source_path.write_bytes(b"Authored changed original; no real PDF")
    else:
        fixture.source_path.unlink()
    before = snapshot(fixture.database)
    with pytest.raises(NumericalSourceError):
        binding.repository.bind(case.record.id, case.artifact.id, fixture.user)
    assert snapshot(fixture.database) == before


def test_quarantined_table_support_cannot_borrow_an_earlier_valid_binding(
    binding: StoredBindingFixture,
):
    fixture, case = binding.source, binding.case
    wrong = fixture.draft.model_copy(update={"period_header": fixture.draft.row_label})
    rejected = NumericalContextStorage(fixture.source).save(wrong, fixture.user)
    assert rejected.inspection.state == "QUARANTINED"
    before = snapshot(fixture.database)
    with pytest.raises(NumericalSourceError):
        binding.repository.bind(rejected.id, case.artifact.id, fixture.user)
    assert snapshot(fixture.database) == before


def test_unavailable_database_is_distinct_and_sanitized(binding: StoredBindingFixture):
    fixture, case = binding.source, binding.case

    def unavailable():
        raise psycopg.OperationalError("Authored private connection diagnostic must not escape")

    source = NumericalRepository(
        fixture.database, fixture.source.storage, fixture.source.configuration, connect=unavailable
    )
    with pytest.raises(NumericalUnavailable, match="storage is unavailable") as error:
        NumericalEvidenceBindingRepository(source).bind(
            case.record.id, case.artifact.id, fixture.user
        )
    assert "private" not in str(error.value)
