"""Authored unpublished drafts and complete role/word projections, not research gold."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.tests.test_numerical_acceptance_models import acceptance
from backend.tests.test_publication_engine import ALPHA, BETA, amendment, authored, create
from backend.tests.test_publication_projection import CountingEncoder
from regintel.entities.models import canonical_bytes
from regintel.numerical.draft_models import (
    NumericalPublicationDraft,
    NumericalPublicationDraftRequest,
    NumericalPublicationEntry,
    numerical_draft_identity,
    numerical_observation_identity,
)
from regintel.numerical.draft_projection import (
    NumericalGraphPreparation,
    NumericalRetrievalPreparation,
    _phrase_pieces,
    prepare_numerical_graph,
    prepare_numerical_retrieval,
)
from regintel.publication.graph import graph_data
from regintel.publication.models import FilingSnapshot


def draft(tmp_path, parent=None):
    accepted = acceptance(tmp_path)
    proof = accepted.candidate.preparation.proposed_input.proof
    filing = FilingSnapshot(
        filing_id=proof.filing_id,
        filing_version_id=proof.filing_version_id,
        parse_version_id=proof.parse_version_id,
        source_sha256=proof.source_sha256,
        document_type="PROSPECTUS",
        published_on="2026-10-01",
    )
    request = NumericalPublicationDraftRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=parent.id if parent else None,
        candidate_ids=(accepted.record.request.candidate_id,),
    )
    actor = str(uuid4())
    return NumericalPublicationDraft(
        id=numerical_draft_identity(request, "d" * 64, actor, 1),
        request=request,
        configuration_sha256="d" * 64,
        prepared_by=actor,
        auth_version=1,
        parent=parent,
        entries=(
            NumericalPublicationEntry(
                id=numerical_observation_identity(request.candidate_ids[0]),
                acceptance=accepted,
                filing=filing,
            ),
        ),
    )


def test_draft_preserves_complete_decimal_proof_without_publication(tmp_path):
    value = draft(tmp_path)
    proposed = value.entries[0].acceptance.candidate.preparation.proposed_input
    assert len(proposed.gate.evidence_ids) > 16
    assert proposed.quantity.raw_value == "2,500.20"
    assert value.entries[0].filing.published_on != proposed.quantity.period.end_date
    assert (
        value.state == "UNPUBLISHED_DRAFT"
        and not value.publishes_fact
        and not value.corpus_committed
    )
    assert NumericalPublicationDraft.model_validate_json(canonical_bytes(value)) == value


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "parent",
        "candidate",
        "actor",
        "entry_id",
        "source",
        "amendment",
        "acceptance",
        "publish",
        "commit",
    ],
)
def test_draft_cannot_mix_identity_source_acceptance_or_publication(tmp_path, change):
    payload = draft(tmp_path).model_dump(mode="json")
    if change == "id":
        payload["id"] = str(uuid4())
    elif change == "parent":
        payload["request"]["parent_corpus_version_id"] = str(uuid4())
    elif change == "candidate":
        payload["request"]["candidate_ids"] = [str(uuid4())]
    elif change == "actor":
        payload["prepared_by"] = str(uuid4())
    elif change == "entry_id":
        payload["entries"][0]["id"] = str(uuid4())
    elif change == "source":
        payload["entries"][0]["filing"]["source_sha256"] = "e" * 64
    elif change == "amendment":
        payload["entries"][0]["filing"]["document_type"] = "ADDENDUM"
    elif change == "acceptance":
        payload["entries"][0]["acceptance"]["record"]["state"] = "REJECTED"
    elif change == "publish":
        payload["publishes_fact"] = True
    else:
        payload["corpus_committed"] = True
    with pytest.raises(ValidationError):
        NumericalPublicationDraft.model_validate(payload)


@pytest.mark.parametrize("field", ["entries", "prepared_by", "quantity", "configuration_sha256"])
def test_request_cannot_supply_observations_actor_values_or_configuration(field):
    with pytest.raises(ValidationError):
        NumericalPublicationDraftRequest.model_validate(
            {
                "idempotency_key": str(uuid4()),
                "parent_corpus_version_id": None,
                "candidate_ids": [str(uuid4())],
                field: "forged",
            }
        )


def test_complete_retrieval_keeps_all_words_and_table_cell_roles(tmp_path):
    value = draft(tmp_path)
    projection = prepare_numerical_retrieval(value, CountingEncoder(), "b" * 64)
    proof = value.entries[0].acceptance.candidate.preparation.proposed_input.proof
    expected = {word.evidence.id for p in proof.phrases for word in p.words}
    actual = {span.evidence_id for c in projection.numerical_chunks for span in c.supports}
    assert expected == actual and len(actual) > 16
    assert projection.legacy_chunks == () and not projection.publishes_fact
    assert all(
        chunk.token_count <= 450 and chunk.text == " ".join(s.quote for s in chunk.supports)
        for chunk in projection.numerical_chunks
    )
    assert {cell for c in projection.numerical_chunks for cell in c.cell_ids} == {
        cell.artifact_cell_id for cell in proof.cells
    }
    assert prepare_numerical_retrieval(value, CountingEncoder(), "b" * 64) == projection
    assert (
        NumericalRetrievalPreparation.model_validate_json(canonical_bytes(projection)) == projection
    )


@pytest.mark.parametrize(
    "change",
    [
        "drop",
        "quote",
        "role",
        "page",
        "cell",
        "identity",
        "vector",
        "lexical",
        "token",
        "duplicate",
    ],
)
def test_retrieval_cannot_drop_or_mix_proof_or_publish_invalid_vectors(tmp_path, change):
    projection = prepare_numerical_retrieval(draft(tmp_path), CountingEncoder(), "b" * 64)
    payload = projection.model_dump(mode="json")
    chunk = payload["numerical_chunks"][0]
    if change == "drop":
        payload["numerical_chunks"].pop()
    elif change == "quote":
        chunk["supports"][0]["quote"] = "forged"
    elif change == "role":
        chunk["role"] = "value" if chunk["role"] != "value" else "row_label"
    elif change == "page":
        chunk["source"]["page_id"] = str(uuid4())
    elif change == "cell":
        chunk["cell_ids"] = [str(uuid4())]
    elif change == "identity":
        chunk["observation_id"] = str(uuid4())
    elif change == "vector":
        chunk["embedding"] = [0.0] * 384
    elif change == "lexical":
        chunk["term_counts"] = {"invented": 1}
    elif change == "token":
        chunk["token_count"] = 513
    else:
        payload["numerical_chunks"].append(chunk.copy())
    with pytest.raises(ValidationError):
        NumericalRetrievalPreparation.model_validate(payload)


@pytest.mark.parametrize("effect_type", ["ADD", "CORRECT", "SUPPLEMENT", "SUPERSEDE", "REMOVE"])
def test_parent_history_graph_and_chunks_remain_exact_and_version_explicit(tmp_path, effect_type):
    original_parent, child, lineage, effect = amendment(effect_type)
    parent = create(
        child, parent=original_parent, child=True, lineages=(lineage,), effects=(effect,)
    )
    original = canonical_bytes(parent)
    value = draft(tmp_path, parent)
    graph = prepare_numerical_graph(value)
    legacy = graph_data(parent)
    assert all(node in graph.data.nodes for node in legacy.nodes)
    assert all(edge in graph.data.edges for edge in legacy.edges)
    assert any(e.source == parent.id and e.target == value.id for e in graph.data.edges)
    projection = prepare_numerical_retrieval(
        value, CountingEncoder(), parent.configuration.embedding_manifest_sha256
    )
    assert {c.observation_id for c in projection.legacy_chunks} == {
        o.id for o in parent.observations
    }
    assert value.parent.active_observation_ids == parent.active_observation_ids
    assert value.parent.lineages == parent.lineages and value.parent.effects == parent.effects
    assert canonical_bytes(parent) == original
    payload = projection.model_dump(mode="json")
    payload["legacy_chunks"].pop()
    with pytest.raises(ValidationError):
        NumericalRetrievalPreparation.model_validate(payload)
    with pytest.raises(ValueError):
        prepare_numerical_retrieval(value, CountingEncoder(), "f" * 64)


def test_graph_retains_every_role_word_geometry_and_accepted_decision(tmp_path):
    value = draft(tmp_path)
    prepared = prepare_numerical_graph(value)
    entry = value.entries[0]
    proof = entry.acceptance.candidate.preparation.proposed_input.proof
    supports = [
        json.loads(edge.payload) for edge in prepared.data.edges if edge.label == "SUPPORTED_BY"
    ]
    assert len(supports) == sum(len(p.words) for p in proof.phrases)
    assert {s["word"]["evidence"]["id"] for s in supports} == {
        word.evidence.id for p in proof.phrases for word in p.words
    }
    assert all(s["word"]["evidence"]["boxes"] for s in supports)
    assert any(
        node.id == entry.acceptance.record.id and node.label == "Decision"
        for node in prepared.data.nodes
    )
    assert prepare_numerical_graph(value) == prepared
    payload = prepared.model_dump(mode="json")
    payload["draft_sha256"] = "f" * 64
    with pytest.raises(ValidationError):
        NumericalGraphPreparation.model_validate(payload)


def test_long_unicode_source_word_is_split_without_truncation(tmp_path):
    value = draft(tmp_path)
    phrase = value.entries[0].acceptance.candidate.preparation.proposed_input.proof.phrases[0]
    word = phrase.words[0]
    text = "印度😀e\u0301" * 250
    reference = word.reference.model_copy(update={"end": len(text), "quote": text})
    evidence = word.evidence.model_copy(
        update={"span": word.evidence.span.model_copy(update={"end": len(text), "quote": text})}
    )
    long_phrase = phrase.model_copy(
        update={"words": (word.model_copy(update={"reference": reference, "evidence": evidence}),)}
    )
    pieces = _phrase_pieces(long_phrase, CountingEncoder())
    assert len(pieces) > 1
    assert "".join(s.quote for group in pieces for s in group) == text
    assert all(
        CountingEncoder().token_count(" ".join(s.quote for s in group)) <= 450 for group in pieces
    )


def test_graph_rejects_entity_and_observation_identity_collisions(tmp_path):
    value = draft(tmp_path)
    parent = create(authored(f"{ALPHA} supplies to {BETA}."))
    observed = parent.observations[0].model_copy(update={"subject_entity_id": value.entries[0].id})
    parent = parent.model_copy(update={"observations": (observed,)})
    request = value.request.model_copy(update={"parent_corpus_version_id": parent.id})
    mixed = NumericalPublicationDraft.model_validate(
        value.model_dump(mode="python")
        | {
            "parent": parent,
            "request": request,
            "id": numerical_draft_identity(
                request, value.configuration_sha256, value.prepared_by, value.auth_version
            ),
        }
    )
    with pytest.raises(ValueError, match="identities cannot collide"):
        prepare_numerical_graph(mixed)
