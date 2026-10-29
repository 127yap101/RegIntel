"""Administrator wire path over owned PostgreSQL and authored geometry, never gold data."""

import base64
import hashlib
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_review_storage import (
    reviewed_case as reviewed_case,
)
from backend.tests.integration.test_numerical_context_review_storage import (
    supported_header as supported_header,
)
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_review_http import bearer
from backend.tests.integration.test_numerical_review_http import client_case as client_case
from backend.tests.integration.test_publication_storage import configuration, prepared
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.contracts.models import SuccessEnvelope
from regintel.evidence.api import EvidenceData, EvidenceService
from regintel.evidence.repository import EvidenceRepository
from regintel.main import create_app
from regintel.numerical.acceptance_models import StoredNumericalAcceptance
from regintel.numerical.candidate_models import StoredNumericalCandidate
from regintel.numerical.publication_models import NumericalPublicationPreparation
from regintel.numerical.review_api import NumericalReviewPacket
from regintel.numerical.review_models import ReviewedNumericalContext
from regintel.publication.models import CandidateSelection, PublicationRequest
from regintel.publication.repository import PublicationRepository

pytestmark = pytest.mark.integration


def test_saved_gate_through_review_candidate_acceptance_and_common_publication(
    client_case, tmp_path
):
    client, case, gate, proposal, numerical, settings = client_case
    headers = bearer(case.source.user, settings)
    path = f"/v1/admin/numerical/gates/{gate.result.id}"
    packet = SuccessEnvelope[NumericalReviewPacket].model_validate(
        client.get(path, headers=headers).json()
    )
    assert packet.data.review is None
    reviewed = client.post(path + "/review", headers=headers, json=proposal.model_dump(mode="json"))
    assert reviewed.status_code == 200
    review = SuccessEnvelope[ReviewedNumericalContext].model_validate(reviewed.json()).data
    assert review.request == proposal
    response = client.get(path + "/publication-input", headers=headers)
    assert response.status_code == 200
    preparation = (
        SuccessEnvelope[NumericalPublicationPreparation].model_validate(response.json()).data
    )
    assert preparation.state == "READY_FOR_ADAPTER" and preparation.proposed_input is not None
    body = {"gate_run_id": gate.result.id, "prepared_input_id": preparation.proposed_input.id}
    response = client.post(path + "/candidates", headers=headers, json=body)
    assert response.status_code == 200
    candidate = SuccessEnvelope[StoredNumericalCandidate].model_validate(response.json()).data
    assert candidate.preparation == preparation
    decision_path = path + f"/candidates/{candidate.record.id}/acceptance"
    assert client.get(decision_path, headers=headers).status_code == 404
    decision = {
        "candidate_id": candidate.record.id,
        "decision": "ACCEPT",
        "evidence_ids": list(gate.result.evidence_ids),
        "note": "Authored administrator workflow; no real filing/content approval.",
    }
    response = client.post(decision_path, headers=headers, json=decision)
    assert response.status_code == 200
    accepted = SuccessEnvelope[StoredNumericalAcceptance].model_validate(response.json()).data
    assert accepted.candidate == candidate and accepted.record.state == "ACCEPTED_UNPUBLISHED"
    assert client.get(decision_path, headers=headers).json()["data"] == accepted.model_dump(
        mode="json"
    )
    assert client.post(decision_path, headers=headers, json=decision).json()[
        "data"
    ] == accepted.model_dump(mode="json")
    restored = SuccessEnvelope[NumericalReviewPacket].model_validate(
        client.get(path, headers=headers).json()
    )
    assert restored.data.review == review

    publication = PublicationRepository(case.source.database, numerical.source)
    request = PublicationRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=None,
        selections=(
            CandidateSelection(
                candidate_run_id=gate.result.id,
                candidate_id=candidate.record.id,
                review_id=accepted.record.id,
            ),
        ),
    )
    manifest = publication.build(request, configuration(), case.source.user)
    result = publication.finalize(
        manifest.id,
        configuration(),
        case.source.user,
        prepared(publication, case.source.user, manifest),
    )
    assert result.new_acceptances[0].accepted == accepted and publication.published() == manifest

    source = EvidenceService(EvidenceRepository(case.source.database), numerical.source.storage)
    app = create_app(
        auth_service=AuthService(PostgreSQLAuthRepository(case.source.database), settings),
        evidence_service=source,
    )
    with TestClient(app) as reader:
        word = restored.data.binding.phrases[0].words[0]
        response = reader.get(f"/v1/evidence/{word.evidence.id}", headers=headers)
        assert response.status_code == 200
        evidence = SuccessEnvelope[EvidenceData].model_validate(response.json())
        assert evidence.data.record == word.evidence
        original = reader.get(
            f"/v1/filing-versions/{word.evidence.source.filing_version_id}/source.pdf",
            headers=headers,
        )
        assert original.status_code == 200
        assert hashlib.sha256(original.content).hexdigest() == restored.data.binding.source_sha256
        payload = {
            "fixture_notice": (
                "Authored engineering fixture: blank two-page PDF and declared word geometry; "
                "not transcription truth, financial gold, real content approval or prices."
            ),
            "manifest": manifest.model_dump(mode="json"),
            "private_meta": packet.meta.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
            "pdf_base64": base64.b64encode(original.content).decode("ascii"),
        }
    # Round-trip the actual HTTP/build wire as a portable authored verification artifact.
    fixture = tmp_path / "numerical-admin-wire.json"
    fixture.write_bytes(
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    reloaded = json.loads(fixture.read_bytes())
    assert reloaded["manifest"] == manifest.model_dump(mode="json")
