"""Authenticated source applicability requirements and immutable attestations."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ContractModel, ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId
from regintel.numerical.applicability_models import (
    NumericalApplicabilityRequest,
    NumericalApplicabilityRequirements,
    ReviewedNumericalApplicability,
)
from regintel.numerical.applicability_repository import NumericalApplicabilityRepository
from regintel.numerical.gate_models import ApplicabilityGateInput
from regintel.numerical.repository import NumericalRepository
from regintel.numerical.resolved_gate_repository import ResolvedNumericalGateRepository
from regintel.numerical.review_api import NumericalReviewPacket, perform


class NumericalApplicabilityGateResult(ContractModel):
    base_gate_run_id: CanonicalId
    applicability_review_id: CanonicalId
    packet: NumericalReviewPacket


def create_numerical_applicability_router(
    auth: AuthService | None, source: NumericalRepository | None
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/numerical/gates", tags=["numerical applicability"])
    administrator = user_dependency(auth, admin=True)
    errors: dict[int | str, dict[str, object]] = {
        status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409, 422, 503)
    }

    def ready() -> NumericalApplicabilityRepository:
        if source is None:
            raise HTTPException(503, "Numerical applicability storage is unavailable.")
        return NumericalApplicabilityRepository(source)

    @router.get(
        "/{gate_id}/applicability/requirements",
        response_model=SuccessEnvelope[NumericalApplicabilityRequirements],
        responses=errors,
    )
    def requirements(
        gate_id: CanonicalId, request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[NumericalApplicabilityRequirements]:
        return SuccessEnvelope(
            data=perform(lambda: ready().requirements(gate_id, user)), meta=response_meta(request)
        )

    @router.get(
        "/{gate_id}/applicability",
        response_model=SuccessEnvelope[ReviewedNumericalApplicability],
        responses=errors,
    )
    def history(
        gate_id: CanonicalId, request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[ReviewedNumericalApplicability]:
        return SuccessEnvelope(
            data=perform(lambda: ready().get(gate_id, user)), meta=response_meta(request)
        )

    @router.post(
        "/{gate_id}/applicability",
        response_model=SuccessEnvelope[ReviewedNumericalApplicability],
        responses=errors,
    )
    def save(
        gate_id: CanonicalId,
        body: NumericalApplicabilityRequest,
        request: Request,
        user: Annotated[User, Depends(administrator)],
    ) -> SuccessEnvelope[ReviewedNumericalApplicability]:
        if body.gate_run_id != gate_id:
            raise HTTPException(409, "The applicability decision differs from the selected gate.")
        return SuccessEnvelope(
            data=perform(lambda: ready().save(body, user)), meta=response_meta(request)
        )

    @router.post(
        "/{gate_id}/applicability/gate",
        response_model=SuccessEnvelope[NumericalApplicabilityGateResult],
        responses=errors,
    )
    def resolve(
        gate_id: CanonicalId, request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[NumericalApplicabilityGateResult]:
        def run() -> NumericalApplicabilityGateResult:
            store = ready()
            gate = ResolvedNumericalGateRepository(store.source).run(gate_id, user)
            # A rerun can refer to an already separately confirmed gate.
            from regintel.numerical.repository import NumericalNotFound
            from regintel.numerical.review_repository import NumericalContextReviewRepository

            try:
                review = NumericalContextReviewRepository(store.source).get(gate.result.id, user)
            except NumericalNotFound:
                review = None
            assert isinstance(gate.source_input, ApplicabilityGateInput)
            return NumericalApplicabilityGateResult(
                base_gate_run_id=gate.source_input.base_result.id,
                applicability_review_id=gate.source_input.applicability.id,
                packet=NumericalReviewPacket(
                    gate=gate.result, binding=gate.source_input.binding, review=review
                ),
            )

        return SuccessEnvelope(data=perform(run), meta=response_meta(request))

    return router
