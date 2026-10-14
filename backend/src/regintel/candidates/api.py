"""Admin-only raw proposal catalogue and deterministic extraction runs."""

from typing import Annotated, Self

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, model_validator

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.candidates.models import MetricDefinition
from regintel.candidates.records import CandidateRun
from regintel.candidates.repository import (
    CandidateAuthorizationError,
    CandidateConflict,
    CandidateNotFound,
    CandidateRepository,
    CandidateSourceError,
    CandidateUnavailable,
)
from regintel.contracts.http import response_meta
from regintel.contracts.models import ContractModel, ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId


class MetricReceipt(ContractModel):
    metric_id: CanonicalId
    already_exists: bool


class MetricEnvelope(SuccessEnvelope[MetricReceipt]):
    pass


class ExtractionRequest(ContractModel):
    entity_run_id: CanonicalId
    metric_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=100)] = ()

    @model_validator(mode="after")
    def distinct_metrics(self) -> Self:
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("Metric references must be distinct.")
        return self


class CandidateEnvelope(SuccessEnvelope[CandidateRun]):
    pass


class CandidateService:
    def __init__(self, repository: CandidateRepository) -> None:
        self.repository = repository


def create_candidate_router(
    auth: AuthService | None, service: CandidateService | None
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/candidates", tags=["candidate extraction"])
    admin = user_dependency(auth, admin=True)

    def configured() -> CandidateService:
        if service is None:
            raise HTTPException(503, "Candidate extraction is unavailable.")
        return service

    def mapped(error: Exception) -> HTTPException:
        if isinstance(error, CandidateAuthorizationError):
            return HTTPException(403, "Administrator approval is unavailable.")
        if isinstance(error, CandidateUnavailable):
            return HTTPException(503, "Candidate extraction is unavailable.")
        if isinstance(error, CandidateNotFound):
            return HTTPException(404, "Candidate source, metric or run not found.")
        if isinstance(error, CandidateConflict):
            return HTTPException(409, "Candidate request conflicts with stored state.")
        if isinstance(error, (CandidateSourceError, ValueError)):
            return HTTPException(422, "Candidate source or shape is invalid or exceeds a bound.")
        return HTTPException(503, "Candidate extraction is unavailable.")

    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 422, 500, 503)
    }
    failures = (
        CandidateAuthorizationError,
        CandidateConflict,
        CandidateNotFound,
        CandidateSourceError,
        CandidateUnavailable,
        psycopg.Error,
        ValueError,
        OSError,
    )

    def envelope(request: Request, run: CandidateRun) -> CandidateEnvelope:
        meta = response_meta(request)
        return CandidateEnvelope(
            data=run,
            meta=meta.model_copy(
                update={
                    "versions": meta.versions.model_copy(
                        update={"parse_version_id": run.parse_version_id}
                    )
                }
            ),
        )

    @router.post("/metrics", response_model=MetricEnvelope, responses=errors)
    def register_metric(
        request: Request,
        body: MetricDefinition,
        user: Annotated[User, Depends(admin)],
        candidates: Annotated[CandidateService, Depends(configured)],
    ) -> MetricEnvelope:
        try:
            created = candidates.repository.register_metric(body, user)
        except failures as error:
            raise mapped(error) from None
        return MetricEnvelope(
            data=MetricReceipt(metric_id=body.id, already_exists=not created),
            meta=response_meta(request),
        )

    @router.post("/runs", response_model=CandidateEnvelope, responses=errors)
    def extract(
        request: Request,
        body: ExtractionRequest,
        user: Annotated[User, Depends(admin)],
        candidates: Annotated[CandidateService, Depends(configured)],
    ) -> CandidateEnvelope:
        try:
            run = candidates.repository.extract(body.entity_run_id, body.metric_ids, user)
        except failures as error:
            raise mapped(error) from None
        return envelope(request, run)

    @router.get("/runs/{run_id}", response_model=CandidateEnvelope, responses=errors)
    def get_run(
        request: Request,
        run_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        candidates: Annotated[CandidateService, Depends(configured)],
    ) -> CandidateEnvelope:
        try:
            run = candidates.repository.get_run(run_id)
            if run is None:
                raise CandidateNotFound()
        except failures as error:
            raise mapped(error) from None
        return envelope(request, run)

    return router
