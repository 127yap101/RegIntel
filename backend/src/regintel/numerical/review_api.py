"""Private numerical proposals and audited decisions; no corpus publication endpoint."""

import hashlib
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import model_validator

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ContractModel, ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId
from regintel.entities.models import canonical_bytes
from regintel.numerical.acceptance_models import (
    NumericalAcceptanceRequest,
    StoredNumericalAcceptance,
)
from regintel.numerical.acceptance_repository import NumericalAcceptanceRepository
from regintel.numerical.candidate_models import NumericalCandidateRequest, StoredNumericalCandidate
from regintel.numerical.candidate_repository import NumericalCandidateRepository
from regintel.numerical.evidence_binding_models import NumericalEvidenceBinding
from regintel.numerical.gate_models import BoundNumericalGateRun
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.publication_input_repository import NumericalPublicationInputRepository
from regintel.numerical.publication_models import NumericalPublicationPreparation
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalSourceError,
    NumericalUnavailable,
)
from regintel.numerical.review_models import (
    NumericalContextReviewRequest,
    ReviewedNumericalContext,
)
from regintel.numerical.review_repository import (
    NumericalContextReviewRepository,
    NumericalReviewConflict,
)


class NumericalReviewPacket(ContractModel):
    gate: BoundNumericalGateRun
    binding: NumericalEvidenceBinding
    review: ReviewedNumericalContext | None

    @model_validator(mode="after")
    def selected_gate_membership(self) -> "NumericalReviewPacket":
        identities = tuple(
            sorted({word.evidence.id for phrase in self.binding.phrases for word in phrase.words})
        )
        if (
            self.binding.id != self.gate.evidence_binding_id
            or self.binding.parse_version_id != self.gate.parse_version_id
            or identities != self.gate.evidence_ids
            or (self.review is not None and self.review.request.gate_run_id != self.gate.id)
            or (
                self.review is not None
                and (
                    self.review.gate_input_sha256 != self.gate.input_sha256
                    or self.review.gate_result_sha256
                    != hashlib.sha256(canonical_bytes(self.gate)).hexdigest()
                    or self.review.request.evidence_ids != self.gate.evidence_ids
                )
            )
        ):
            raise ValueError("A review packet must retain its selected gate and exact binding.")
        return self


def perform[T](work: Callable[[], T]) -> T:
    try:
        return work()
    except NumericalAuthorizationError:
        raise HTTPException(403, "Current administrator access is required.") from None
    except NumericalNotFound:
        raise HTTPException(404, "The selected numerical review is unavailable.") from None
    except NumericalReviewConflict:
        raise HTTPException(
            409, "The review conflicts with its gate, source or stored decision."
        ) from None
    except (NumericalSourceError, NumericalUnavailable, ValueError, OSError):
        raise HTTPException(503, "Numerical review prerequisites could not be verified.") from None


def create_numerical_review_router(
    auth: AuthService | None, repository: NumericalContextReviewRepository | None
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/numerical/gates", tags=["numerical context review"])
    administrator = user_dependency(auth, admin=True)
    errors: dict[int | str, dict[str, object]] = {
        status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409, 422, 503)
    }

    def ready() -> NumericalContextReviewRepository:
        if repository is None:
            raise HTTPException(503, "Numerical review storage is unavailable.")
        return repository

    def packet(gate_id: str, user: User) -> NumericalReviewPacket:
        store = ready()
        gate = BoundNumericalGateRepository(store.source).get(gate_id, user)
        try:
            review = store.get(gate_id, user)
        except NumericalNotFound:
            review = None
        return NumericalReviewPacket(
            gate=gate.result, binding=gate.source_input.binding, review=review
        )

    @router.get(
        "/{gate_id}", response_model=SuccessEnvelope[NumericalReviewPacket], responses=errors
    )
    def read(
        gate_id: CanonicalId, request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[NumericalReviewPacket]:
        # Historical inspection never promotes retained inputs to a fresh confirmation.
        return SuccessEnvelope(
            data=perform(lambda: packet(gate_id, user)), meta=response_meta(request)
        )

    @router.post(
        "/{gate_id}/review",
        response_model=SuccessEnvelope[ReviewedNumericalContext],
        responses=errors,
    )
    def review(
        gate_id: CanonicalId,
        body: NumericalContextReviewRequest,
        request: Request,
        user: Annotated[User, Depends(administrator)],
    ) -> SuccessEnvelope[ReviewedNumericalContext]:
        if body.gate_run_id != gate_id:
            raise HTTPException(409, "The submitted review differs from the selected gate.")
        return SuccessEnvelope(
            data=perform(lambda: ready().save(body, user)), meta=response_meta(request)
        )

    @router.get(
        "/{gate_id}/publication-input",
        response_model=SuccessEnvelope[NumericalPublicationPreparation],
        responses=errors,
    )
    def publication_input(
        gate_id: CanonicalId, request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[NumericalPublicationPreparation]:
        return SuccessEnvelope(
            data=perform(
                lambda: NumericalPublicationInputRepository(ready().source).prepare(gate_id, user)
            ),
            meta=response_meta(request),
        )

    @router.post(
        "/{gate_id}/candidates",
        response_model=SuccessEnvelope[StoredNumericalCandidate],
        responses=errors,
    )
    def create_candidate(
        gate_id: CanonicalId,
        body: NumericalCandidateRequest,
        request: Request,
        user: Annotated[User, Depends(administrator)],
    ) -> SuccessEnvelope[StoredNumericalCandidate]:
        if body.gate_run_id != gate_id:
            raise HTTPException(409, "The selected gate differs from the candidate request.")
        return SuccessEnvelope(
            data=perform(lambda: NumericalCandidateRepository(ready().source).save(body, user)),
            meta=response_meta(request),
        )

    @router.get(
        "/{gate_id}/candidates/{candidate_id}",
        response_model=SuccessEnvelope[StoredNumericalCandidate],
        responses=errors,
    )
    def read_candidate(
        gate_id: CanonicalId,
        candidate_id: CanonicalId,
        request: Request,
        user: Annotated[User, Depends(administrator)],
    ) -> SuccessEnvelope[StoredNumericalCandidate]:
        def selected() -> StoredNumericalCandidate:
            candidate = NumericalCandidateRepository(ready().source).get(candidate_id, user)
            if candidate.record.request.gate_run_id != gate_id:
                raise NumericalNotFound("The candidate does not belong to the selected gate.")
            return candidate

        return SuccessEnvelope(data=perform(selected), meta=response_meta(request))

    @router.post(
        "/{gate_id}/candidates/{candidate_id}/acceptance",
        response_model=SuccessEnvelope[StoredNumericalAcceptance],
        responses=errors,
    )
    def decide_candidate(
        gate_id: CanonicalId,
        candidate_id: CanonicalId,
        body: NumericalAcceptanceRequest,
        request: Request,
        user: Annotated[User, Depends(administrator)],
    ) -> SuccessEnvelope[StoredNumericalAcceptance]:
        if body.candidate_id != candidate_id:
            raise HTTPException(409, "The decision differs from the selected candidate.")

        def decide() -> StoredNumericalAcceptance:
            source = ready().source
            candidate = NumericalCandidateRepository(source).get(candidate_id, user)
            if candidate.record.request.gate_run_id != gate_id:
                raise NumericalNotFound("The candidate does not belong to the selected gate.")
            return NumericalAcceptanceRepository(source).save(body, user)

        return SuccessEnvelope(data=perform(decide), meta=response_meta(request))

    @router.get(
        "/{gate_id}/candidates/{candidate_id}/acceptance",
        response_model=SuccessEnvelope[StoredNumericalAcceptance],
        responses=errors,
    )
    def read_acceptance(
        gate_id: CanonicalId,
        candidate_id: CanonicalId,
        request: Request,
        user: Annotated[User, Depends(administrator)],
    ) -> SuccessEnvelope[StoredNumericalAcceptance]:
        def selected_acceptance() -> StoredNumericalAcceptance:
            stored = NumericalAcceptanceRepository(ready().source).get(candidate_id, user)
            if stored.candidate.record.request.gate_run_id != gate_id:
                raise NumericalNotFound("The acceptance does not belong to the selected gate.")
            return stored

        return SuccessEnvelope(data=perform(selected_acceptance), meta=response_meta(request))

    return router
