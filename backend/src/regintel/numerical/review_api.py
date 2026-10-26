"""Private HTTP access to staged reviews; no acceptance or publication endpoint."""

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
from regintel.numerical.evidence_binding_models import NumericalEvidenceBinding
from regintel.numerical.gate_models import BoundNumericalGateRun
from regintel.numerical.gate_repository import BoundNumericalGateRepository
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

    return router
