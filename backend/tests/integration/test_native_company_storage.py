"""Native registry/current gates in an owned fictional corpus, never human approval."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.integration import test_numerical_context_storage as contexts
from backend.tests.integration.test_native_context_storage import (
    NativeStoredFixture,
    prepare_native_context,
)
from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.native_company_fixtures import company_registration
from backend.tests.test_numerical_context import Options
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.entities.api import EntityService
from regintel.entities.models import NativeCompanyRegistration, canonical_bytes
from regintel.entities.repository import (
    EntityAuthorizationError,
    EntityConflict,
    EntityRepository,
)
from regintel.main import create_app
from regintel.numerical.context_storage import NumericalContextStorage
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.parsing.native_repository import NativeM1Producer

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class NativeRegistryFixture:
    native: NativeStoredFixture
    repository: EntityRepository
    registration: NativeCompanyRegistration
    client: TestClient
    settings: AuthSettings


@pytest.fixture
def company(auth_database, tmp_path, monkeypatch):
    original = contexts.authored
    monkeypatch.setattr(
        contexts,
        "authored",
        lambda path: original(path, Options(unit="(INR in million)", currency=())),
    )
    inspection = contexts.prepare_inspection(auth_database, tmp_path, approvals="no_issuer")
    native = prepare_native_context(inspection, tmp_path)
    NativeM1Producer(inspection.source).run(native.job.id, native.result, inspection.user)
    registration = company_registration(native.result, native.record.source_input.draft)
    repository = EntityRepository(auth_database)
    settings = AuthSettings(jwt_secret=SecretStr("7" * 64))
    app = create_app(
        auth_service=AuthService(PostgreSQLAuthRepository(auth_database), settings),
        entity_service=EntityService(repository),
    )
    with TestClient(app) as client:
        yield NativeRegistryFixture(native, repository, registration, client, settings)


def headers(company, user=None):
    user = user or company.native.source.user
    return {"Authorization": "Bearer " + issue_token(user, company.settings)}


def test_native_registration_uses_existing_endpoint_and_exact_snapshot_without_facts(company):
    body = company.registration
    response = company.client.post(
        "/v1/admin/entities", json=body.model_dump(mode="json"), headers=headers(company)
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"entity_id": body.id, "already_exists": False}
    before = snapshot(company.native.source.database)
    assert company.client.post(
        "/v1/admin/entities", json=body.model_dump(mode="json"), headers=headers(company)
    ).json()["data"]["already_exists"]
    assert snapshot(company.native.source.database) == before
    registry = company.repository.snapshot()
    assert registry.entities == (body,) and registry.revision == 1
    with company.repository.connect() as connection:
        row = connection.execute(
            "SELECT registration_bytes,registered_by FROM "
            "regintel.entity_registrations WHERE id=%s",
            (UUID(body.id),),
        ).fetchone()
        assert row is not None and bytes(row[0]) == canonical_bytes(body)
        assert row[1] == company.native.source.user.id
        for table in ("fact_observations", "acceptance_audits", "corpus_versions"):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)


def test_native_company_support_resolves_issuer_in_a_fresh_context_without_overwriting_old(company):
    source = company.native.source
    old = company.native.record
    assert next(c.state for c in old.inspection.checks if c.code == "ISSUER") == "REVIEW"
    assert company.repository.register(company.registration, source.user)
    retained = NumericalContextStorage(source.source)
    fresh = retained.save(old.source_input.draft, source.user)
    assert fresh.id != old.id and retained.get(old.id, source.user) == old
    assert isinstance(fresh.source_input.registry.entities[0], NativeCompanyRegistration)
    gate = BoundNumericalGateRepository(source.source).run(
        fresh.id, company.native.result.artifact.id, source.user
    )
    assert gate.result.state == "READY_FOR_REVIEW"
    assert all(check.state == "PASS" for check in gate.result.checks)
    assert not gate.result.acceptance_eligible and not gate.result.mandatory_m1_validation_complete


def test_concurrent_same_native_registration_creates_one_identity(company):
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [
            pool.submit(
                company.repository.register, company.registration, company.native.source.user
            )
            for _ in range(2)
        ]
        outcomes = [call.result(timeout=60) for call in calls]
    assert sorted(outcomes) == [False, True]
    assert company.repository.snapshot().entities == (company.registration,)


@pytest.mark.parametrize("change", ["learner", "forged_role", "stale", "inactive", "demoted"])
def test_native_registration_requires_current_administrator_before_writes(company, change):
    source = company.native.source
    user = source.user
    if change in {"learner", "forged_role"}:
        user = source.learner
        if change == "forged_role":
            user = replace(user, role="admin")
    elif change == "stale":
        user = replace(user, auth_version=user.auth_version + 1)
    else:
        with company.repository.connect() as connection:
            connection.execute(
                "UPDATE regintel.users SET is_active=%s,role=%s WHERE id=%s",
                (change != "inactive", "learner" if change == "demoted" else "admin", user.id),
            )
    before = snapshot(source.database)
    with pytest.raises(EntityAuthorizationError):
        company.repository.register(company.registration, user)
    assert snapshot(source.database) == before


def test_identifier_and_immutable_payload_conflicts_roll_back_complete_registration(company):
    assert company.repository.register(company.registration, company.native.source.user)
    before = snapshot(company.native.source.database)
    for changed in (
        company.registration.model_copy(update={"id": str(uuid4())}),
        company.registration.model_copy(update={"review_note": "Different audited note"}),
    ):
        with pytest.raises(EntityConflict):
            company.repository.register(changed, company.native.source.user)
        assert snapshot(company.native.source.database) == before


@pytest.mark.parametrize(
    "change",
    [
        "name_gap",
        "partial",
        "order",
        "foreign",
        "parse",
        "keyword",
        "alias",
        "unknown_schema",
        "hash",
        "short_name",
        "blank_note",
    ],
)
def test_direct_database_gate_rejects_unsupported_native_registration(company, change):
    raw = company.registration.model_dump(mode="json")
    if change == "blank_note":
        raw["review_note"] = " \n\t"
    elif change == "short_name":
        raw["legal_name"] = "Authored"
        raw["legal_name_support"]["spans"] = raw["legal_name_support"]["spans"][:1]
    elif change == "name_gap":
        for role in ("legal_name_support", "issuer_header"):
            raw[role]["spans"].pop(1)
        raw["legal_name"] = "Authored Limited"
    elif change == "partial":
        for role in ("legal_name_support", "issuer_header"):
            span = raw[role]["spans"][0]
            span.update(quote=span["quote"][1:], start=1)
        raw["legal_name"] = raw["legal_name"][1:]
    elif change == "order":
        for role in ("legal_name_support", "issuer_header"):
            raw[role]["spans"][:2] = reversed(raw[role]["spans"][:2])
        raw["legal_name"] = "Solar Authored Limited"
    elif change == "foreign":
        for role in ("legal_name_support", "issuer_header"):
            raw[role]["spans"][0]["evidence_id"] = str(uuid4())
    elif change == "parse":
        for role in ("legal_name_support", "issuer_header"):
            raw[role]["parse_version_id"] = str(uuid4())
    elif change == "keyword":
        raw["issuer_header"]["spans"][3]["quote"] = "OTHER"
    elif change == "alias":
        raw["aliases"] = [{"name": "Authored", "support": raw["issuer_header"]["spans"][0]}]
    elif change == "unknown_schema":
        raw["schema_version"] = "native-company-registration-999"
    body = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = "0" * 64 if change == "hash" else hashlib.sha256(body).hexdigest()
    before = snapshot(company.native.source.database)
    with company.repository.connect() as connection, pytest.raises(psycopg.Error):
        with connection.transaction():
            connection.execute(
                "INSERT INTO regintel.entity_registrations "
                "(id,registration_bytes,registration_sha256,registered_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s)",
                (
                    UUID(raw["id"]),
                    body,
                    digest,
                    company.native.source.user.id,
                    company.native.source.user.auth_version,
                ),
            )
            connection.execute(
                "INSERT INTO regintel.entity_identifiers(entity_id,kind,value) VALUES(%s,%s,%s)",
                (UUID(raw["id"]), "CIN", raw["identifiers"][0]["value"]),
            )
    assert snapshot(company.native.source.database) == before


@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_native_registry_history_is_append_only(company, action):
    company.repository.register(company.registration, company.native.source.user)
    before = snapshot(company.native.source.database)
    command = {
        "UPDATE": "UPDATE regintel.entity_registrations SET registration_bytes=registration_bytes",
        "DELETE": "DELETE FROM regintel.entity_registrations",
        "TRUNCATE": "TRUNCATE regintel.entity_registrations CASCADE",
    }[action]
    with company.repository.connect() as connection, pytest.raises(psycopg.errors.CheckViolation):
        with connection.transaction():
            connection.execute(command)
    assert snapshot(company.native.source.database) == before
