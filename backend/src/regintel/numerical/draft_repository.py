"""Locked, read-only draft preparation from current accepted numerical candidates."""

import hashlib
from pathlib import Path
from uuid import UUID

import psycopg

from regintel.auth.types import User
from regintel.db.migrations import MigrationError
from regintel.evidence.projection import ProjectionError
from regintel.ingestion.storage import UploadError
from regintel.numerical.acceptance_repository import _read as read_acceptance
from regintel.numerical.acceptance_repository import acceptance_configuration_sha256
from regintel.numerical.candidate_repository import candidate_storage_configuration_sha256
from regintel.numerical.draft_models import (
    NumericalPublicationDraft,
    NumericalPublicationDraftRequest,
    NumericalPublicationEntry,
    numerical_draft_identity,
    numerical_observation_identity,
)
from regintel.numerical.publication_input_repository import prepare_in_transaction
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
)
from regintel.numerical.review_repository import NumericalReviewConflict
from regintel.publication.engine import PublicationConflict
from regintel.publication.repository import PUBLICATION_LOCK_ID, PublicationRepository


def draft_configuration_sha256() -> str:
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256(acceptance_configuration_sha256().encode("ascii"))
    for name in ("draft_models.py", "draft_repository.py", "draft_projection.py"):
        body = (package / name).read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


class NumericalPublicationDraftRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def prepare(
        self, request: NumericalPublicationDraftRequest, user: User
    ) -> NumericalPublicationDraft:
        request = NumericalPublicationDraftRequest.model_validate(request.model_dump(mode="python"))
        try:
            with self.source.connect() as connection, connection.transaction():
                _authorize(connection, user)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (PUBLICATION_LOCK_ID,))
                connection.execute(
                    "LOCK TABLE regintel.entity_registrations,regintel.metric_definitions,"
                    "regintel.numeric_metric_policies,regintel.numerical_context_reviews,"
                    "regintel.numerical_candidates,regintel.numerical_acceptances IN SHARE MODE"
                )
                if PublicationRepository._head(connection) != request.parent_corpus_version_id:
                    raise NumericalReviewConflict("Select the current published parent explicitly.")
                parent = (
                    PublicationRepository._manifest(
                        connection, request.parent_corpus_version_id, published=True
                    )
                    if request.parent_corpus_version_id is not None
                    else None
                )
                entries = []
                for candidate_id in request.candidate_ids:
                    accepted = read_acceptance(connection, candidate_id)
                    candidate = accepted.candidate
                    if accepted.record.state != "ACCEPTED_UNPUBLISHED":
                        raise NumericalReviewConflict(
                            "Publication draft requires explicit acceptance."
                        )
                    fresh = prepare_in_transaction(
                        connection, self.source, candidate.record.request.gate_run_id, user
                    )
                    if (
                        fresh != candidate.preparation
                        or candidate.record.storage_configuration_sha256
                        != candidate_storage_configuration_sha256()
                        or accepted.record.configuration_sha256 != acceptance_configuration_sha256()
                    ):
                        raise NumericalReviewConflict(
                            "Accepted source or preparation configuration changed."
                        )
                    prepared = fresh.proposed_input
                    assert prepared is not None
                    filing = PublicationRepository._filing(
                        connection, parse_id=prepared.proof.parse_version_id
                    )
                    row = connection.execute(
                        "SELECT declared_parent_filing_version_id "
                        "FROM regintel.filing_versions WHERE id=%s",
                        (UUID(filing.filing_version_id),),
                    ).fetchone()
                    if (
                        row is None
                        or row[0] is not None
                        or filing.document_type in {"ADDENDUM", "CORRIGENDUM"}
                    ):
                        raise NumericalReviewConflict(
                            "Numerical amendments require the versioned lineage/effect adapter."
                        )
                    entries.append(
                        NumericalPublicationEntry(
                            id=numerical_observation_identity(candidate_id),
                            acceptance=accepted,
                            filing=filing,
                        )
                    )
                configuration = draft_configuration_sha256()
                return NumericalPublicationDraft(
                    id=numerical_draft_identity(
                        request, configuration, str(user.id), user.auth_version
                    ),
                    request=request,
                    configuration_sha256=configuration,
                    prepared_by=str(user.id),
                    auth_version=user.auth_version,
                    parent=parent,
                    entries=tuple(entries),
                )
        except (
            NumericalAuthorizationError,
            NumericalNotFound,
            NumericalSourceError,
            NumericalReviewConflict,
        ):
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable("Numerical draft storage is unavailable.") from None
        except (
            psycopg.Error,
            ValueError,
            OSError,
            UploadError,
            ProjectionError,
            PublicationConflict,
        ):
            raise NumericalReviewConflict(
                "The complete numerical publication draft could not be verified."
            ) from None
