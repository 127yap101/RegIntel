"""Administrator gate audits and staged reviews; publication remains unavailable."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ContractModel, ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId
from regintel.validation.models import NumericMetricPolicy, ReviewDecision, ValidationRun
from regintel.validation.repository import (
    ValidationAuthorizationError,
    ValidationConflict,
    ValidationNotFound,
    ValidationRepository,
    ValidationSourceError,
    ValidationUnavailable,
)


class PolicyReceipt(ContractModel):
    policy_id: CanonicalId
    already_exists: bool


class PolicyEnvelope(SuccessEnvelope[PolicyReceipt]):
    pass


class ValidationRequest(ContractModel):
    candidate_run_id: CanonicalId


class ValidationData(ContractModel):
    run: ValidationRun
    reviews: tuple[ReviewDecision, ...]


class ValidationEnvelope(SuccessEnvelope[ValidationData]):
    pass


class ReviewReceipt(ContractModel):
    review_id: CanonicalId
    already_exists: bool


class ReviewEnvelope(SuccessEnvelope[ReviewReceipt]):
    pass


class ValidationService:
    def __init__(self, repository: ValidationRepository) -> None:
        self.repository = repository


def create_validation_router(
    auth: AuthService | None, service: ValidationService | None
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/validation", tags=["validation and staged review"])
    admin = user_dependency(auth, admin=True)

    def configured() -> ValidationService:
        if service is None:
            raise HTTPException(503, "Validation is unavailable.")
        return service

    def mapped(error: Exception) -> HTTPException:
        if isinstance(error, ValidationAuthorizationError):
            return HTTPException(403, "Administrator approval is unavailable.")
        if isinstance(error, ValidationUnavailable):
            return HTTPException(503, "Validation is unavailable.")
        if isinstance(error, ValidationNotFound):
            return HTTPException(404, "Validation source or run not found.")
        if isinstance(error, ValidationConflict):
            return HTTPException(409, "Validation or review conflicts with stored state.")
        if isinstance(error, (ValidationSourceError, ValueError)):
            return HTTPException(422, "Validation support is invalid or exceeds a bound.")
        return HTTPException(503, "Validation is unavailable.")

    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 422, 500, 503)
    }
    failures = (
        ValidationAuthorizationError,
        ValidationUnavailable,
        ValidationNotFound,
        ValidationConflict,
        ValidationSourceError,
        ValueError,
        psycopg.Error,
        OSError,
    )

    def envelope(
        request: Request, run: ValidationRun, reviews: tuple[ReviewDecision, ...]
    ) -> ValidationEnvelope:
        meta = response_meta(request)
        return ValidationEnvelope(
            data=ValidationData(run=run, reviews=reviews),
            meta=meta.model_copy(
                update={
                    "versions": meta.versions.model_copy(
                        update={"parse_version_id": run.parse_version_id}
                    )
                }
            ),
        )

    @router.post("/policies", response_model=PolicyEnvelope, responses=errors)
    def register_policy(
        request: Request,
        body: NumericMetricPolicy,
        user: Annotated[User, Depends(admin)],
        validator: Annotated[ValidationService, Depends(configured)],
    ) -> PolicyEnvelope:
        try:
            created = validator.repository.register_policy(body, user)
        except failures as error:
            raise mapped(error) from None
        return PolicyEnvelope(
            data=PolicyReceipt(policy_id=body.id, already_exists=not created),
            meta=response_meta(request),
        )

    @router.post("/runs", response_model=ValidationEnvelope, responses=errors)
    def validate(
        request: Request,
        body: ValidationRequest,
        user: Annotated[User, Depends(admin)],
        validator: Annotated[ValidationService, Depends(configured)],
    ) -> ValidationEnvelope:
        try:
            run = validator.repository.validate(body.candidate_run_id, user)
            reviews = validator.repository.reviews(run.id)
        except failures as error:
            raise mapped(error) from None
        return envelope(request, run, reviews)

    @router.get("/runs/{run_id}", response_model=ValidationEnvelope, responses=errors)
    def get_run(
        request: Request,
        run_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        validator: Annotated[ValidationService, Depends(configured)],
    ) -> ValidationEnvelope:
        try:
            run = validator.repository.get_run(run_id)
            if run is None:
                raise ValidationNotFound()
            reviews = validator.repository.reviews(run.id)
        except failures as error:
            raise mapped(error) from None
        return envelope(request, run, reviews)

    @router.post("/reviews", response_model=ReviewEnvelope, responses=errors)
    def review(
        request: Request,
        body: ReviewDecision,
        user: Annotated[User, Depends(admin)],
        validator: Annotated[ValidationService, Depends(configured)],
    ) -> ReviewEnvelope:
        try:
            created = validator.repository.review(body, user)
        except failures as error:
            raise mapped(error) from None
        return ReviewEnvelope(
            data=ReviewReceipt(review_id=body.id, already_exists=not created),
            meta=response_meta(request),
        )

    return router
