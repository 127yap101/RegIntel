"""Disposable inspection history; synthetic registry/policy approvals are engineering fixtures."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from backend.tests.integration.test_numerical_context_storage import (
    InspectionContext,
    snapshot,
)
from backend.tests.integration.test_numerical_context_storage import (
    inspection as inspection,
)
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.db.migrations import DatabaseConnection, connect_database
from regintel.numerical.context_records import NumericalContextRecord, context_record_id
from regintel.numerical.context_storage import NumericalContextStorage
from regintel.numerical.repository import NumericalAuthorizationError, NumericalSourceError
from regintel.validation.models import NumericMetricPolicy
from regintel.validation.repository import ValidationRepository

pytestmark = pytest.mark.integration


def authority(fixture: InspectionContext) -> dict[str, str]:
    return {
        key: value
        for key, value in snapshot(fixture.database).items()
        if key not in {"numerical_context_records", "numerical_context_pages"}
    }


def rows(fixture: InspectionContext) -> tuple[int, int]:
    with connect_database(fixture.database) as connection:
        row = connection.execute(
            "SELECT "
            "(SELECT count(*) FROM regintel.numerical_context_records),"
            "(SELECT count(*) FROM regintel.numerical_context_pages)"
        ).fetchone()
        assert row is not None
        return cast(tuple[int, int], row)


def test_history_roundtrip_replay_preserves_all_other_authority(inspection: InspectionContext):
    repository = NumericalContextStorage(inspection.source)
    before = authority(inspection)
    record = repository.save(inspection.draft, inspection.user)
    assert rows(inspection) == (1, 1)
    assert record.inspection.state == "SUPPORTED_PROPOSAL"
    assert record.source_input.draft == inspection.draft
    assert record.source_input.metric is not None and record.source_input.policy is not None
    assert record.source_input.registry.revision == 1
    assert repository.get(record.id, inspection.user) == record
    assert repository.save(inspection.draft, inspection.user) == record
    assert not record.acceptance_eligible and not record.mandatory_m1_validation_complete
    assert rows(inspection) == (1, 1) and authority(inspection) == before


@pytest.mark.parametrize("workers_count", [2, 4])
def test_concurrent_identical_records_keep_original_submission(
    inspection: InspectionContext, workers_count: int
):
    repository = NumericalContextStorage(inspection.source)
    before = authority(inspection)
    with ThreadPoolExecutor(max_workers=workers_count) as workers:
        futures = [
            workers.submit(repository.save, inspection.draft, inspection.user)
            for _ in range(workers_count)
        ]
        records = [future.result(timeout=40) for future in futures]
    assert all(record == records[0] for record in records) and rows(inspection) == (1, 1)
    assert authority(inspection) == before


@pytest.mark.parametrize("inspection", ["no_policy"], indirect=True)
def test_new_policy_creates_new_history_without_rewriting_old_snapshot(
    inspection: InspectionContext,
):
    repository = NumericalContextStorage(inspection.source)
    before = repository.save(inspection.draft, inspection.user)
    assert before.inspection.state == "REVIEW_REQUIRED" and before.source_input.policy is None
    policy = NumericMetricPolicy(
        id=str(uuid4()),
        metric_id=inspection.draft.metric_id,
        quantity_kind="MONEY",
        period_kind="DURATION",
        allowed_unit_labels=("million",),
        review_note="Authored engineering-only policy; no real human review claim.",
    )
    ValidationRepository(inspection.database).register_policy(policy, inspection.user)
    after = repository.save(inspection.draft, inspection.user)
    assert after.id != before.id and after.source_input.policy == policy
    assert after.inspection.state == "SUPPORTED_PROPOSAL"
    assert repository.get(before.id, inspection.user) == before
    assert rows(inspection) == (2, 2)


def test_wrong_column_is_retained_as_quarantine_with_prior_history(inspection: InspectionContext):
    repository = NumericalContextStorage(inspection.source)
    before = repository.save(inspection.draft, inspection.user)
    wrong = inspection.draft.model_copy(update={"period_header": inspection.draft.row_label})
    invalid = repository.save(wrong, inspection.user)
    assert invalid.id != before.id and invalid.inspection.state == "QUARANTINED"
    assert invalid.inspection.quantity is None
    assert repository.get(before.id, inspection.user) == before
    assert rows(inspection) == (2, 2)


def test_cross_version_context_is_quarantined_even_with_identical_pdf_bytes(
    inspection: InspectionContext,
):
    source = inspection.source
    # Ordinary ingestion rejects conflicting metadata for identical bytes. Construct an
    # inconsistent authored version only here to exercise the independent context gate.
    other_version, other_filing = uuid4(), uuid4()
    original = source.get(inspection.draft.issuer_header.capture_id, inspection.user)
    with connect_database(inspection.database) as connection:
        connection.execute(
            "INSERT INTO regintel.filings(id,company_name_raw) VALUES(%s,'Other authored issuer')",
            (other_filing,),
        )
        connection.execute(
            "INSERT INTO regintel.filing_versions(id,filing_id,source_blob_id,document_type) "
            "VALUES(%s,%s,%s,'PROSPECTUS')",
            (other_version, other_filing, UUID(original.source_blob_id)),
        )
        capture = connection.execute(
            "SELECT raw_capture_bytes FROM regintel.numerical_page_captures WHERE id=%s",
            (UUID(inspection.draft.issuer_header.capture_id),),
        ).fetchone()
    assert capture is not None
    other = source.save(str(other_version), bytes(capture[0]), 2, inspection.user)
    phrase = inspection.draft.issuer_header
    draft = inspection.draft.model_copy(
        update={
            "issuer_header": phrase.model_copy(
                update={
                    "words": tuple(
                        ref.model_copy(update={"capture_id": other.id}) for ref in phrase.words
                    )
                }
            )
        }
    )
    before = authority(inspection)
    record = NumericalContextStorage(source).save(draft, inspection.user)
    assert record.inspection.state == "QUARANTINED" and record.inspection.quantity is None
    assert record.inspection.checks[0].state == "FAIL"
    assert rows(inspection) == (1, 2) and authority(inspection) == before


@pytest.mark.parametrize("change", ["learner", "forged_role", "stale", "inactive", "demoted"])
def test_current_admin_required_for_history_reads_and_writes(
    inspection: InspectionContext, change: str
):
    repository = NumericalContextStorage(inspection.source)
    record = repository.save(inspection.draft, inspection.user)
    user = inspection.user
    if change in {"learner", "forged_role"}:
        user = (
            inspection.learner if change == "learner" else replace(inspection.learner, role="admin")
        )
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
        repository.save(inspection.draft, user)
    with pytest.raises(NumericalAuthorizationError):
        repository.get(record.id, user)
    assert snapshot(inspection.database) == before


def test_fresh_admin_version_can_read_prior_submission(inspection: InspectionContext):
    repository = NumericalContextStorage(inspection.source)
    record = repository.save(inspection.draft, inspection.user)
    with connect_database(inspection.database) as connection:
        connection.execute(
            "UPDATE regintel.users SET auth_version=auth_version+1 WHERE id=%s",
            (inspection.user.id,),
        )
    current = PostgreSQLAuthRepository(inspection.database).get_by_username("admin")
    assert current is not None and current.auth_version != record.auth_version
    assert repository.get(record.id, current) == record
    assert repository.save(inspection.draft, current) == record


@pytest.mark.parametrize("change", ["modified", "missing"])
def test_save_reverifies_pdf_but_historical_read_preserves_record(
    inspection: InspectionContext, change: str
):
    repository = NumericalContextStorage(inspection.source)
    record = repository.save(inspection.draft, inspection.user)
    if change == "modified":
        inspection.source_path.write_bytes(inspection.source_path.read_bytes() + b"altered")
    else:
        inspection.source_path.unlink()
    before = snapshot(inspection.database)
    assert repository.get(record.id, inspection.user) == record
    with pytest.raises(NumericalSourceError):
        repository.save(inspection.draft, inspection.user)
    assert snapshot(inspection.database) == before


@pytest.mark.parametrize("table", ["numerical_context_records", "numerical_context_pages"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_context_history_cannot_be_changed_removed_or_truncated(
    inspection: InspectionContext, table: str, operation: str
):
    repository = NumericalContextStorage(inspection.source)
    record = repository.save(inspection.draft, inspection.user)
    statement = {
        "UPDATE": sql.SQL("UPDATE regintel.{} SET {}={}").format(
            sql.Identifier(table),
            sql.Identifier("auth_version" if table.endswith("records") else "ordinal"),
            sql.Identifier("auth_version" if table.endswith("records") else "ordinal"),
        ),
        "DELETE": sql.SQL("DELETE FROM regintel.{}").format(sql.Identifier(table)),
        "TRUNCATE": sql.SQL("TRUNCATE regintel.{} CASCADE").format(sql.Identifier(table)),
    }[operation]
    before = snapshot(inspection.database)
    with connect_database(inspection.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(statement)
    assert repository.get(record.id, inspection.user) == record
    assert snapshot(inspection.database) == before


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def insert_diagnostic(
    connection: DatabaseConnection,
    record: NumericalContextRecord,
    change: str,
    *,
    pages: bool = True,
) -> None:
    """Rehash invalid authored SQL requests to test guards independently of the repository."""
    source = record.source_input.model_dump(mode="json")
    result = record.inspection.model_dump(mode="json")
    if change == "registry":
        source["registry"]["sha256"] = "0" * 64
    elif change == "metric":
        source["metric"]["label"] = "Unregistered replacement"
    elif change == "policy":
        source["policy"]["allowed_unit_labels"] = ["crore"]
    elif change == "page":
        source["pages"][0]["capture"]["words"][0]["orig"] = "changed"
    elif change == "eligible":
        result["acceptance_eligible"] = True
    elif change == "mandatory":
        result["mandatory_m1_validation_complete"] = True
    elif change == "review":
        result["review_required"] = False
    elif change == "checks":
        result["checks"] = list(reversed(result["checks"]))
    elif change == "state":
        result["checks"][0]["state"] = "FAIL"
    source_bytes = canonical(source)
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    draft_sha = hashlib.sha256(canonical(source["draft"])).hexdigest()
    result.update(source_input_sha256=source_sha, draft_sha256=draft_sha, draft=source["draft"])
    key = f"{draft_sha}:{source_sha}:{result['configuration_sha256']}"
    result["id"] = str(UUID(bytes=hashlib.sha256(key.encode()).digest()[:16], version=4))
    result_bytes = canonical(result)
    seal = "a" * 64
    identity = context_record_id(result["id"], seal)
    if change == "id":
        identity = str(uuid4())
    input_sha = "0" * 64 if change == "input_hash" else source_sha
    result_sha = "0" * 64 if change == "result_hash" else hashlib.sha256(result_bytes).hexdigest()
    connection.execute(
        """INSERT INTO regintel.numerical_context_records
        (id,filing_version_id,source_blob_id,source_sha256,input_bytes,input_sha256,
         inspection_id,inspection_bytes,inspection_sha256,context_configuration_sha256,
         storage_configuration_sha256,page_count,submitted_by,auth_version)
         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            UUID(identity),
            UUID(record.filing_version_id),
            UUID(record.source_blob_id),
            record.source_sha256,
            source_bytes,
            input_sha,
            UUID(result["id"]),
            result_bytes,
            result_sha,
            result["configuration_sha256"],
            seal,
            len(source["pages"]),
            record.submitted_by,
            record.auth_version + 1 if change == "actor" else record.auth_version,
        ),
    )
    if pages:
        for ordinal, page in enumerate(source["pages"]):
            connection.execute(
                "INSERT INTO regintel.numerical_context_pages "
                "(record_id,ordinal,capture_id) VALUES(%s,%s,%s)",
                (UUID(identity), ordinal, UUID(page["id"])),
            )


@pytest.mark.parametrize(
    "change",
    [
        "registry",
        "metric",
        "policy",
        "page",
        "eligible",
        "mandatory",
        "review",
        "checks",
        "state",
        "id",
        "input_hash",
        "result_hash",
        "actor",
    ],
)
def test_database_rejects_rehashed_wrong_snapshots_and_promotions(
    inspection: InspectionContext, change: str
):
    record = NumericalContextStorage(inspection.source).save(inspection.draft, inspection.user)
    before = snapshot(inspection.database)
    with connect_database(inspection.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            insert_diagnostic(connection, record, change)
    assert snapshot(inspection.database) == before


def test_unsealed_page_membership_rolls_back_the_record(inspection: InspectionContext):
    record = NumericalContextStorage(inspection.source).save(inspection.draft, inspection.user)
    before = snapshot(inspection.database)
    with connect_database(inspection.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            insert_diagnostic(connection, record, "none", pages=False)
    assert snapshot(inspection.database) == before


def test_page_membership_cannot_be_appended_after_sealing(inspection: InspectionContext):
    record = NumericalContextStorage(inspection.source).save(inspection.draft, inspection.user)
    before = snapshot(inspection.database)
    with connect_database(inspection.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO regintel.numerical_context_pages "
                "(record_id,ordinal,capture_id) VALUES(%s,0,%s)",
                (UUID(record.id), UUID(record.source_input.pages[0].id)),
            )
    assert snapshot(inspection.database) == before
