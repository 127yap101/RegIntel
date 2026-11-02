"""Owned historical discovery; fictional source declarations do not approve real filings."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from backend.tests.integration import test_numerical_context_storage as contexts
from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_review_storage import (
    reviewed_case as reviewed_case,
)
from backend.tests.integration.test_numerical_context_review_storage import (
    supported_header as supported_header,
)
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.integration.test_numerical_review_http import bearer
from backend.tests.integration.test_numerical_review_http import client_case as client_case
from regintel.contracts.models import SuccessEnvelope
from regintel.entities.models import EntityRegistration
from regintel.entities.repository import EntityRepository
from regintel.ingestion.jobs import UploadMetadata
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.queue_models import NumericalGateQueuePage, NumericalGateQueueRequest
from regintel.numerical.queue_repository import NumericalGateQueueRepository
from regintel.numerical.repository import NumericalAuthorizationError, NumericalUnavailable

pytestmark = pytest.mark.integration
PATH = "/v1/admin/numerical/gates"
LABEL = 'Authored <script>alert("queue")</script> Corporation'


@pytest.fixture(autouse=True)
def hostile_intake_label(monkeypatch):
    original = contexts.prepare_inspection

    def prepare(*args, **kwargs):
        return original(
            *args,
            **(kwargs | {"metadata": UploadMetadata(company_name_raw=LABEL, document_type="RHP")}),
        )

    monkeypatch.setattr(contexts, "prepare_inspection", prepare)


def extra_gate(case, original):
    # A separate evidenced engineering registration changes the live snapshot.
    # Its new gate records unresolved freshness rather than upgrading old inputs.
    entity = original.source_input.current_context.registry.entities[0]
    EntityRepository(case.source.database).register(
        EntityRegistration(
            id=str(uuid4()),
            kind="COMPANY",
            legal_name=entity.legal_name,
            legal_name_support=entity.legal_name_support,
            identifiers=(),
            review_note="Separate authored registry entry; no real entity or human-review claim.",
        ),
        case.source.user,
    )
    return BoundNumericalGateRepository(case.source.source).run(
        original.result.context_record_id, original.result.parse_version_id, case.source.user
    )


def read(client, headers, **params):
    response = client.get(PATH, headers=headers, params=params)
    assert response.status_code == 200, response.status_code
    return SuccessEnvelope[NumericalGateQueuePage].model_validate(response.json())


def test_queue_is_current_admin_only_and_has_no_authority_or_preparation_writes(client_case):
    client, case, gate, _, _, settings = client_case
    before = snapshot(case.source.database)
    assert client.get(PATH).status_code == 401
    assert client.get(PATH, headers=bearer(case.source.learner, settings)).status_code == 403
    value = read(client, bearer(case.source.user, settings))
    assert value.data.scope == "RETAINED_HISTORY_ONLY"
    assert len(value.data.items) == 1 and not value.data.has_more
    item = value.data.items[0]
    assert item.gate == gate.result and item.review is None
    assert item.filing_version_id == gate.source_input.binding.filing_version_id
    assert item.company_name_raw == LABEL and not item.gate.acceptance_eligible
    assert all(value is None for value in value.meta.versions.model_dump().values())
    repository = NumericalGateQueueRepository(case.source.source)
    selection = NumericalGateQueueRequest(state="ALL", review="ALL", query="", offset=0, limit=20)
    for actor in (case.source.learner, replace(case.source.user, auth_version=999)):
        with pytest.raises(NumericalAuthorizationError):
            repository.queue(selection, actor)
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize(
    "query,expected",
    [
        ("aUtHoReD", 1),
        ("<script>", 1),
        ("%", 0),
        ("_", 0),
        ("' OR 1=1 --", 0),
        ("missing company", 0),
    ],
)
def test_company_search_is_literal_intake_metadata_and_empty_is_not_unavailable(
    client_case, query, expected
):
    client, case, _, _, _, settings = client_case
    before = snapshot(case.source.database)
    page = read(client, bearer(case.source.user, settings), query=query).data
    assert len(page.items) == expected and page.query == query
    assert snapshot(case.source.database) == before


def test_actual_multi_gate_pagination_is_distinct_and_cannot_confirm_stale_context(client_case):
    client, case, gate, proposal, _, settings = client_case
    others = [extra_gate(case, gate), extra_gate(case, gate)]
    assert all(value.result.state == "REVIEW_REQUIRED" for value in others)
    expected = sorted([gate.result.id, *(value.result.id for value in others)])
    before = snapshot(case.source.database)
    headers = bearer(case.source.user, settings)
    for offset, identity in enumerate(expected):
        page = read(client, headers, review="ALL", offset=offset, limit=1).data
        assert [item.gate.id for item in page.items] == [identity]
        assert page.offset == offset and page.limit == 1
        assert page.has_more == (offset < 2)
    assert not read(client, headers, review="ALL", offset=3, limit=1).data.items
    assert len(read(client, headers, state="REVIEW_REQUIRED").data.items) == 2
    assert read(client, headers, state="READY_FOR_REVIEW").data.items[0].gate == gate.result
    # A historically ready queue row is not fresh approval after a registry change.
    response = client.post(
        PATH + f"/{gate.result.id}/review", headers=headers, json=proposal.model_dump(mode="json")
    )
    assert response.status_code == 409
    assert snapshot(case.source.database) == before


def test_recorded_decisions_filter_without_promoting_history_and_capture_actual_wire(
    client_case, tmp_path
):
    client, case, gate, proposal, _, settings = client_case
    headers = bearer(case.source.user, settings)
    initial = read(client, headers)
    initial_packet = client.get(PATH + f"/{gate.result.id}", headers=headers).json()
    confirmed = client.post(
        PATH + f"/{gate.result.id}/review", headers=headers, json=proposal.model_dump(mode="json")
    )
    assert confirmed.status_code == 200
    extra = extra_gate(case, gate)
    rejected = proposal.model_copy(
        update={
            "gate_run_id": extra.result.id,
            "decision": "REJECT",
            "evidence_ids": extra.result.evidence_ids,
            "note": "Authored unresolved snapshot rejection; not a real financial review.",
        }
    )
    response = client.post(
        PATH + f"/{extra.result.id}/review", headers=headers, json=rejected.model_dump(mode="json")
    )
    assert response.status_code == 200
    # Retain actual pages large enough to exercise the browser's fixed 20-row paging.
    for _ in range(21):
        extra_gate(case, gate)
    before = snapshot(case.source.database)
    pages = {"unreviewed": initial.model_dump(mode="json")}
    for key, params in (
        ("confirmed", {"review": "CONFIRM_CONTEXT"}),
        ("rejected", {"review": "REJECT"}),
        ("all", {"review": "ALL"}),
        ("all_next", {"review": "ALL", "offset": 20}),
        ("empty", {}),
    ):
        value = read(client, headers, **params)
        pages[key] = value.model_dump(mode="json")
    pages["empty"] = read(client, headers, query="missing queue label").model_dump(mode="json")
    assert not pages["empty"]["data"]["items"]
    assert len(pages["confirmed"]["data"]["items"]) == len(pages["rejected"]["data"]["items"]) == 1
    assert len(pages["all"]["data"]["items"]) == 20
    assert len(pages["all_next"]["data"]["items"]) == 3
    assert pages["all"]["data"]["has_more"] and not pages["all_next"]["data"]["has_more"]
    packets = {
        gate.result.id: initial_packet,
        extra.result.id: client.get(PATH + f"/{extra.result.id}", headers=headers).json(),
    }
    assert snapshot(case.source.database) == before
    (tmp_path / "numerical-queue-wire.json").write_text(
        json.dumps(
            {
                "fixture_notice": (
                    "Actual owned PostgreSQL/HTTP engineering capture; fictional issuer, "
                    "authored blank PDF/geometry and hostile intake label. "
                    "Not real review or research gold."
                ),
                "pages": pages,
                "packets": packets,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


@pytest.mark.parametrize(
    "params",
    [
        {"state": "ACCEPTED"},
        {"review": "APPROVE"},
        {"query": "x" * 121},
        {"query": "\x00"},
        {"offset": -1},
        {"offset": 10001},
        {"limit": 0},
        {"limit": 21},
        {"offset": "true"},
    ],
)
def test_queue_http_rejects_unbounded_or_unknown_filters_before_data_reads(client_case, params):
    client, case, _, _, _, settings = client_case
    before = snapshot(case.source.database)
    assert (
        client.get(PATH, headers=bearer(case.source.user, settings), params=params).status_code
        == 422
    )
    assert snapshot(case.source.database) == before


def test_queue_budget_failure_is_explicit_not_an_empty_or_truncated_success(
    client_case, monkeypatch
):
    client, case, _, _, _, settings = client_case
    from regintel.numerical import queue_repository

    monkeypatch.setattr(queue_repository, "MAX_QUEUE_BYTES", 1)
    before = snapshot(case.source.database)
    with pytest.raises(NumericalUnavailable):
        NumericalGateQueueRepository(case.source.source).queue(
            NumericalGateQueueRequest(state="ALL", review="ALL", query="", offset=0, limit=20),
            case.source.user,
        )
    response = client.get(PATH, headers=bearer(case.source.user, settings))
    assert response.status_code == 503 and "data" not in response.json()
    assert snapshot(case.source.database) == before
