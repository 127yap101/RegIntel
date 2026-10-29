"""Native numerical observations in the shared M1 publication transaction."""

import hashlib
import re

from regintel.auth.types import User
from regintel.candidates.records import stable_id
from regintel.contracts.models import QuantitativeValue
from regintel.db.migrations import DatabaseConnection
from regintel.entities.models import canonical_bytes
from regintel.evidence.projection import ProjectionError
from regintel.ingestion.storage import UploadError
from regintel.numerical.acceptance_repository import _read as read_acceptance
from regintel.numerical.acceptance_repository import acceptance_configuration_sha256
from regintel.numerical.candidate_repository import candidate_storage_configuration_sha256
from regintel.numerical.publication_input_repository import prepare_in_transaction
from regintel.numerical.repository import NumericalRepository
from regintel.publication.engine import PublicationConflict, require
from regintel.publication.models import (
    CandidateSelection,
    FilingSnapshot,
    NumericalAcceptanceSnapshot,
    PublishedNumericalObservation,
    native_spans,
)


def approve_numerical(
    connection: DatabaseConnection,
    source: NumericalRepository,
    corpus_id: str,
    selection: CandidateSelection,
    filing: FilingSnapshot,
    user: User,
) -> NumericalAcceptanceSnapshot:
    try:
        accepted = read_acceptance(connection, selection.candidate_id)
        candidate = accepted.candidate
        prepared = candidate.preparation.proposed_input
        assert prepared is not None
        require(
            selection.candidate_run_id == prepared.gate_run_id
            and selection.review_id == accepted.record.id
            and accepted.record.state == "ACCEPTED_UNPUBLISHED",
            "Select the exact native gate/candidate/accepted decision.",
        )
        fresh = prepare_in_transaction(connection, source, prepared.gate_run_id, user)
        require(
            fresh == candidate.preparation
            and candidate.record.storage_configuration_sha256
            == candidate_storage_configuration_sha256()
            and accepted.record.configuration_sha256 == acceptance_configuration_sha256(),
            "Native publication requires fresh complete source/context/acceptance checks.",
        )
        proof, value = prepared.proof, prepared.quantity
        require(
            (
                filing.filing_id,
                filing.filing_version_id,
                filing.parse_version_id,
                filing.source_sha256,
            )
            == (
                proof.filing_id,
                proof.filing_version_id,
                proof.parse_version_id,
                proof.source_sha256,
            ),
            "Native numerical publication requires its exact sealed source.",
        )
        spans = native_spans(proof)

        def phrase(role: str) -> str | None:
            matches = [p for p in proof.phrases if p.role == role]
            return (
                " ".join(w.evidence.span.quote for p in matches for w in p.words)
                if matches
                else None
            )

        raw_unit = phrase("unit_header")
        currency_label = re.search(r"INR|USD|₹|Rs\.", raw_unit or "", re.I)
        quantity = QuantitativeValue(
            raw_value=value.raw_value,
            normalized_value=value.normalized_value,
            raw_unit=raw_unit,
            normalized_unit=value.normalized_unit,
            raw_currency=currency_label[0] if currency_label is not None else None,
            currency=value.currency,
            period=value.period,
            basis=value.basis,
            raw_basis_label=phrase("basis_context"),
            denominator=None,
            stake_kind=None,
            ownership_date=None,
            evidence_ids=tuple(span.evidence_id for span in spans),
        )
        identity = stable_id("published-observation:" + candidate.record.id)
        observation = PublishedNumericalObservation(
            id=identity,
            acceptance_audit_id=stable_id("acceptance:" + identity),
            first_corpus_version_id=corpus_id,
            candidate_id=candidate.record.id,
            candidate_run_id=prepared.gate_run_id,
            parse_version_id=proof.parse_version_id,
            filing_version_id=proof.filing_version_id,
            validation_run_id=accepted.record.id,
            validation_input_sha256=prepared.gate_input_sha256,
            validator_configuration_sha256=accepted.record.configuration_sha256,
            review_id=accepted.record.id,
            kind="numeric_fact",
            subject_entity_id=prepared.subject_entity_id,
            object_entity_id=None,
            relation_type=None,
            metric_id=prepared.metric.id,
            raw_text=value.raw_value,
            quantity=quantity,
            supports=spans,
            context_supports=(),
            source_published_on=filing.published_on,
            native_acceptance_id=accepted.record.id,
            proof=proof,
        )
        return NumericalAcceptanceSnapshot(
            observation=observation, accepted=accepted, fresh_preparation=fresh
        )
    except PublicationConflict:
        raise
    except (ValueError, OSError, UploadError, ProjectionError):
        raise PublicationConflict(
            "Native numerical publication prerequisites changed or are unavailable."
        ) from None


def persist_native(
    connection: DatabaseConnection,
    snapshot: NumericalAcceptanceSnapshot,
    user: User,
) -> None:
    observation = snapshot.observation
    payload = canonical_bytes(snapshot)
    connection.execute(
        "INSERT INTO regintel.native_publication_audits "
        "(id,observation_id,candidate_id,acceptance_id,corpus_version_id,snapshot_bytes,"
        "snapshot_sha256,published_by,auth_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            observation.acceptance_audit_id,
            observation.id,
            observation.candidate_id,
            observation.native_acceptance_id,
            observation.first_corpus_version_id,
            payload,
            hashlib.sha256(payload).hexdigest(),
            user.id,
            user.auth_version,
        ),
    )
