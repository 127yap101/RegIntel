"""Audited applicability storage using authored engineering sources and owned databases."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from pydantic import SecretStr

from backend.tests.integration import test_numerical_context_storage as contexts
from backend.tests.integration.conftest import clear_auth_test_schemas
from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_binding_storage import sealed
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.numerical_binding_fixtures import complete_artifact
from backend.tests.test_numerical_context import Options
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.types import SeedAccount
from regintel.db.migrations import DEFAULT_MIGRATIONS, connect_database, migrate
from regintel.entities.models import EntityRegistration, canonical_bytes
from regintel.entities.repository import EntityRepository
from regintel.numerical import applicability_repository as repository_module
from regintel.numerical import review_repository as review_module
from regintel.numerical.applicability_models import NumericalApplicabilityRequest
from regintel.numerical.applicability_repository import (
    NumericalApplicabilityConflict,
    NumericalApplicabilityRepository,
)
from regintel.numerical.context_storage import NumericalContextStorage
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.repository import NumericalAuthorizationError, NumericalNotFound
from regintel.numerical.review_models import NumericalContextReviewRequest
from regintel.numerical.review_repository import (
    NumericalContextReviewRepository,
    NumericalReviewConflict,
)

pytestmark = pytest.mark.integration


def proposed(requirements):
    return NumericalApplicabilityRequest.model_validate(
        requirements.model_dump(mode="python", exclude={"schema_version", "eligible", "blockers"})
        | {"note": "Authored engineering applicability decision with exact phrase/page coverage."}
    )


@pytest.fixture
def applicability_case(binding):
    source = binding.source
    gate = BoundNumericalGateRepository(source.source).run(
        binding.case.record.id, binding.case.artifact.id, source.user
    )
    repository = NumericalApplicabilityRepository(source.source)
    requirements = repository.requirements(gate.result.id, source.user)
    return binding, gate, proposed(requirements), repository


def test_exact_attestation_replays_and_preserves_all_gate_and_authority_rows(applicability_case):
    binding, gate, request, repository = applicability_case
    source = binding.source
    assert gate.result.state == "REVIEW_REQUIRED"
    before = snapshot(source.database)
    requirements = repository.requirements(gate.result.id, source.user)
    assert requirements.eligible and not requirements.blockers
    assert snapshot(source.database) == before
    review = repository.save(request, source.user)
    after = snapshot(source.database)
    assert after["numerical_applicability_reviews"] != before["numerical_applicability_reviews"]
    for table in before.keys() - {"numerical_applicability_reviews"}:
        assert after[table] == before[table], table
    assert repository.get(gate.result.id, source.user) == review
    assert repository.save(request, source.user) == review
    assert snapshot(source.database) == after
    assert not review.acceptance_eligible
    assert not review.mandatory_m1_validation_complete and not review.publishes_fact
    assert BoundNumericalGateRepository(source.source).get(gate.result.id, source.user) == gate
    with pytest.raises(NumericalReviewConflict):
        NumericalContextReviewRepository(source.source).save(
            NumericalContextReviewRequest(
                gate_run_id=gate.result.id,
                decision="CONFIRM_CONTEXT",
                evidence_ids=gate.result.evidence_ids,
                note="Authored attempt to skip the distinct future resolved-gate implementation.",
            ),
            source.user,
        )
    assert snapshot(source.database) == after


@pytest.mark.parametrize("actor", ["learner", "forged", "stale", "inactive"])
def test_current_administrator_is_required_for_all_entry_points(applicability_case, actor):
    binding, gate, request, repository = applicability_case
    source = binding.source
    user = source.user
    if actor == "learner":
        user = source.learner
    elif actor == "forged":
        user = replace(source.learner, role="admin")
    elif actor == "stale":
        user = replace(source.user, auth_version=source.user.auth_version + 1)
    else:
        with connect_database(source.database) as connection:
            connection.execute("UPDATE regintel.users SET is_active=false WHERE id=%s", (user.id,))
    before = snapshot(source.database)
    for action in (
        lambda: repository.save(request, user),
        lambda: repository.requirements(gate.result.id, user),
        lambda: repository.get(gate.result.id, user),
    ):
        with pytest.raises(NumericalAuthorizationError):
            action()
    assert snapshot(source.database) == before


@pytest.mark.parametrize("change", ["input_hash", "result_hash", "cell", "evidence", "pages"])
def test_forged_or_incomplete_exact_membership_cannot_commit(applicability_case, change):
    binding, _, request, repository = applicability_case
    if change == "input_hash":
        request = request.model_copy(update={"gate_input_sha256": "0" * 64})
    elif change == "result_hash":
        request = request.model_copy(update={"gate_result_sha256": "0" * 64})
    elif change == "cell":
        request = request.model_copy(update={"value_cell_id": request.period_cell_id})
    elif change == "evidence":
        assertion = request.assertions[0]
        request = request.model_copy(
            update={
                "assertions": (
                    assertion.model_copy(
                        update={"evidence_ids": (str(uuid4()), *assertion.evidence_ids[1:])}
                    ),
                    *request.assertions[1:],
                )
            }
        )
    else:
        request = request.model_copy(update={"reviewed_page_indices": (999,)})
    before = snapshot(binding.source.database)
    with pytest.raises(NumericalApplicabilityConflict):
        repository.save(request, binding.source.user)
    assert snapshot(binding.source.database) == before


@pytest.mark.parametrize("inspection", ["no_metric", "no_policy", "no_issuer"], indirect=True)
def test_missing_approvals_cannot_be_replaced_by_applicability(applicability_case):
    binding, gate, request, repository = applicability_case
    before = snapshot(binding.source.database)
    requirements = repository.requirements(gate.result.id, binding.source.user)
    assert not requirements.eligible and requirements.blockers
    with pytest.raises(NumericalApplicabilityConflict):
        repository.save(request, binding.source.user)
    assert snapshot(binding.source.database) == before


def test_concurrent_identical_requests_retain_one_original_actor(applicability_case):
    binding, gate, request, repository = applicability_case
    source = binding.source
    seed_users(
        source.database,
        (SeedAccount("other-applicability-admin", SecretStr("Authored administrator!"), "admin"),),
    )
    other = PostgreSQLAuthRepository(source.database).get_by_username("other-applicability-admin")
    assert other is not None
    barrier = Barrier(2)

    def save(user):
        barrier.wait(timeout=30)
        return repository.save(request, user)

    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(save, user) for user in (source.user, other)]
        reviews = [call.result(timeout=60) for call in calls]
    assert reviews[0] == reviews[1] == repository.get(gate.result.id, other)
    assert reviews[0].reviewed_by in {str(source.user.id), str(other.id)}
    with connect_database(source.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.numerical_applicability_reviews"
        ).fetchone() == (1,)


def test_concurrent_different_requests_conflict_and_retain_one_decision(applicability_case):
    binding, gate, request, repository = applicability_case
    changed = request.model_copy(update={"note": "A different authored applicability note."})
    barrier = Barrier(2)

    def save(proposal):
        barrier.wait(timeout=30)
        try:
            return repository.save(proposal, binding.source.user)
        except NumericalApplicabilityConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(save, item) for item in (request, changed)]
        reviews = [call.result(timeout=60) for call in calls]
    retained = [review for review in reviews if review is not None]
    assert len(retained) == 1
    assert repository.get(gate.result.id, binding.source.user) == retained[0]
    assert retained[0].request in (request, changed)


def test_historical_retry_survives_configuration_and_approval_changes(
    applicability_case, monkeypatch
):
    binding, gate, request, repository = applicability_case
    source = binding.source
    review = repository.save(request, source.user)
    entity = gate.source_input.current_context.registry.entities[0]
    EntityRepository(source.database).register(
        EntityRegistration(
            id=str(uuid4()),
            kind="COMPANY",
            legal_name=entity.legal_name,
            legal_name_support=entity.legal_name_support,
            identifiers=(),
            review_note="Authored additional entity registration for historical replay checks.",
        ),
        source.user,
    )
    monkeypatch.setattr(repository_module, "applicability_configuration_sha256", lambda: "f" * 64)
    before = snapshot(source.database)
    assert repository.get(gate.result.id, source.user) == review
    assert repository.save(request, source.user) == review
    with pytest.raises(NumericalApplicabilityConflict):
        repository.requirements(gate.result.id, source.user)
    assert snapshot(source.database) == before


def test_changed_registry_or_source_blocks_first_attestation(applicability_case, monkeypatch):
    binding, gate, request, repository = applicability_case
    source = binding.source
    before = snapshot(source.database)
    with monkeypatch.context() as patch:
        patch.setattr(review_module, "bound_gate_configuration_sha256", lambda: "f" * 64)
        with pytest.raises(NumericalApplicabilityConflict):
            repository.save(request, source.user)
    original = source.source_path.read_bytes()
    try:
        source.source_path.write_bytes(original + b"authored source tampering")
        with pytest.raises(ValueError):
            repository.save(request, source.user)
    finally:
        source.source_path.write_bytes(original)
    assert snapshot(source.database) == before
    entity = gate.source_input.current_context.registry.entities[0]
    EntityRepository(source.database).register(
        EntityRegistration(
            id=str(uuid4()),
            kind="COMPANY",
            legal_name=entity.legal_name,
            legal_name_support=entity.legal_name_support,
            identifiers=(),
            review_note="Authored additional entity registration before initial applicability.",
        ),
        source.user,
    )
    before = snapshot(source.database)
    with pytest.raises(NumericalApplicabilityConflict, match="changed"):
        repository.save(request, source.user)
    assert snapshot(source.database) == before


@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_attestations_reject_mutation_and_removal(applicability_case, action):
    binding, _, request, repository = applicability_case
    repository.save(request, binding.source.user)
    before = snapshot(binding.source.database)
    statement = {
        "UPDATE": "UPDATE regintel.numerical_applicability_reviews SET id=id",
        "DELETE": "DELETE FROM regintel.numerical_applicability_reviews",
        "TRUNCATE": "TRUNCATE regintel.numerical_applicability_reviews CASCADE",
    }[action]
    with pytest.raises(psycopg.Error), connect_database(binding.source.database) as connection:
        connection.execute(statement)
    assert snapshot(binding.source.database) == before


def test_database_guard_rejects_forged_authority_flags(applicability_case, monkeypatch):
    binding, _, request, repository = applicability_case
    original = repository_module.ReviewedNumericalApplicability

    def forged(**kwargs):
        return original(**kwargs).model_copy(update={"publishes_fact": True})

    monkeypatch.setattr(repository_module, "ReviewedNumericalApplicability", forged)
    before = snapshot(binding.source.database)
    with pytest.raises(NumericalApplicabilityConflict):
        repository.save(request, binding.source.user)
    assert snapshot(binding.source.database) == before


def test_unknown_attestation_is_unavailable_without_writes(applicability_case):
    binding, _, _, repository = applicability_case
    before = snapshot(binding.source.database)
    with pytest.raises(NumericalNotFound):
        repository.get(str(uuid4()), binding.source.user)
    assert snapshot(binding.source.database) == before


def persisted_gate(source):
    record = NumericalContextStorage(source.source).save(source.draft, source.user)
    with connect_database(source.database) as connection:
        owner = connection.execute(
            "SELECT filing_id FROM regintel.filing_versions WHERE id=%s",
            (UUID(record.filing_version_id),),
        ).fetchone()
    assert owner is not None
    case = complete_artifact(record, filing_id=str(owner[0]))
    sealed(source, case)
    return BoundNumericalGateRepository(source.source).run(record.id, case.artifact.id, source.user)


def source_with_options(auth_database, tmp_path, monkeypatch, options):
    original = contexts.authored

    def authored(path):
        case = original(path, options)
        # The authored row cue deliberately agrees with the proposed metric so
        # these cases isolate source-language checks from literal metric checks.
        metric = case.input.metric.model_copy(update={"cue_phrases": (options.row,)})
        return replace(case, input=case.input.model_copy(update={"metric": metric}))

    monkeypatch.setattr(contexts, "authored", authored)
    source = contexts.prepare_inspection(auth_database, tmp_path)
    basis = source.draft.basis_context
    if basis is not None:
        capture_id = source.draft.value.phrase.capture_id
        mapped = basis.model_copy(
            update={
                "words": tuple(
                    ref.model_copy(update={"capture_id": capture_id}) for ref in basis.words
                )
            }
        )
        source = replace(source, draft=source.draft.model_copy(update={"basis_context": mapped}))
    return source


@pytest.mark.parametrize(
    "options",
    [
        Options(row="Illustrative revenue from operations"),
        Options(row="Revenue not from operations"),
        Options(
            basis=(
                "Unless otherwise stated, our restated consolidated financial information applies."
            )
        ),
    ],
    ids=["illustrative", "negated", "unsupported-basis-default"],
)
def test_database_guard_rejects_unsupported_semantics_even_if_application_check_is_skipped(
    auth_database, tmp_path, monkeypatch, options
):
    source = source_with_options(auth_database, tmp_path, monkeypatch, options)
    gate = persisted_gate(source)
    repository = NumericalApplicabilityRepository(source.source)
    requirements = repository.requirements(gate.result.id, source.user)
    assert gate.result.state == "REVIEW_REQUIRED"
    assert not requirements.eligible and requirements.assertions
    assert all(
        check.state == "PASS"
        for check in gate.result.checks
        if check.code not in {"BASIS", "SOURCE_LANGUAGE"}
    )
    request = proposed(requirements)
    before = snapshot(auth_database)
    monkeypatch.setattr(repository_module, "validate_applicability_request", lambda *_: None)
    with pytest.raises(NumericalApplicabilityConflict):
        repository.save(request, source.user)
    assert snapshot(auth_database) == before


@pytest.mark.parametrize(
    "prefix", ["", "Unless stated otherwise or the context requires otherwise, "]
)
def test_database_guard_preserves_supported_basis_and_qualification_words(
    auth_database, tmp_path, monkeypatch, prefix
):
    basis = (
        prefix + "the financial information and financial ratios in this Prospectus are derived "
        "from our Restated Consolidated Summary Statements."
    )
    source = source_with_options(auth_database, tmp_path, monkeypatch, Options(basis=basis))
    gate = persisted_gate(source)
    repository = NumericalApplicabilityRepository(source.source)
    requirements = repository.requirements(gate.result.id, source.user)
    assert requirements.eligible, requirements.blockers
    review = repository.save(proposed(requirements), source.user)
    assert repository.get(gate.result.id, source.user) == review
    kinds = {a.kind for a in review.request.assertions if a.role == "basis_context"}
    assert kinds == ({"BASIS", "QUALIFIED_DEFAULT"} if prefix else {"BASIS"})
    assert BoundNumericalGateRepository(source.source).get(gate.result.id, source.user) == gate


def test_populated_schema23_upgrade_preserves_exact_gate_and_every_existing_table(
    auth_database, tmp_path, monkeypatch
):
    clear_auth_test_schemas(auth_database)
    old = tmp_path / "schema23"
    old.mkdir()
    files = sorted(DEFAULT_MIGRATIONS.glob("*.sql"))[:23]
    assert len(files) == 23
    for file in files:
        (old / file.name).write_bytes(file.read_bytes())
    migrate(auth_database, old)
    source = source_with_options(auth_database, tmp_path / "source", monkeypatch, Options())
    gate = persisted_gate(source)
    before = snapshot(auth_database)
    original_bytes = canonical_bytes(gate)
    before_hash = hashlib.sha256(original_bytes).hexdigest()
    report = migrate(auth_database)
    assert report.already_applied == tuple(range(1, 24))
    assert report.newly_applied == (24,)
    after = snapshot(auth_database)
    assert set(after) - set(before) == {"numerical_applicability_reviews"}
    assert {table: after[table] for table in before} == before
    retained = BoundNumericalGateRepository(source.source).get(gate.result.id, source.user)
    assert canonical_bytes(retained) == original_bytes
    assert hashlib.sha256(canonical_bytes(retained)).hexdigest() == before_hash
    repository = NumericalApplicabilityRepository(source.source)
    required = repository.requirements(gate.result.id, source.user)
    review = repository.save(proposed(required), source.user)
    assert repository.get(gate.result.id, source.user) == review
