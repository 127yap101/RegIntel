"""Authenticated source applicability requirements and immutable attestations."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId
from regintel.numerical.applicability_models import (
    NumericalApplicabilityRequest,
    NumericalApplicabilityRequirements,
    ReviewedNumericalApplicability,
)
from regintel.numerical.applicability_repository import NumericalApplicabilityRepository
from regintel.numerical.repository import NumericalRepository
from regintel.numerical.review_api import perform


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

    return router
