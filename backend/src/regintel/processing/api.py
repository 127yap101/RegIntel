"""Administrator workflow submission, inspection and orphan dispatch."""

from collections.abc import Callable
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.candidates.repository import (
    CandidateNotFound,
    CandidateSourceError,
    CandidateUnavailable,
)
from regintel.contracts.http import response_meta
from regintel.contracts.models import ContractModel, ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId
from regintel.entities.repository import EntityNotFound, EntitySourceError, EntityUnavailable
from regintel.processing.models import ProcessingJob, ProcessingRequest
from regintel.processing.repository import (
    ProcessingConflict,
    ProcessingFailure,
    ProcessingNotFound,
    ProcessingRepository,
    ProcessingUnavailable,
)


class ProcessingEnvelope(SuccessEnvelope[ProcessingJob]):
    pass


class DispatchReceipt(ContractModel):
    dispatched: bool


class DispatchEnvelope(SuccessEnvelope[DispatchReceipt]):
    pass


class ProcessingService:
    def __init__(self, repository: ProcessingRepository, send: Callable[[str], None]) -> None:
        self.repository = repository
        self.send = send


def create_processing_router(
    auth: AuthService | None, service: ProcessingService | None
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/processing", tags=["checkpointed processing"])
    admin = user_dependency(auth, admin=True)

    def configured() -> ProcessingService:
        if service is None:
            raise HTTPException(503, "Processing is unavailable.")
        return service

    failures = (
        ProcessingConflict,
        ProcessingFailure,
        ProcessingNotFound,
        ProcessingUnavailable,
        EntityNotFound,
        EntitySourceError,
        EntityUnavailable,
        CandidateNotFound,
        CandidateSourceError,
        CandidateUnavailable,
        ValueError,
        psycopg.Error,
        OSError,
    )

    def mapped(error: Exception) -> HTTPException:
        if isinstance(error, ProcessingFailure) and error.code == "AUTHORIZATION_CHANGED":
            return HTTPException(403, "Administrator authorization changed.")
        if isinstance(error, (ProcessingUnavailable, EntityUnavailable, CandidateUnavailable)):
            return HTTPException(503, "Processing is unavailable.")
        if isinstance(error, (ProcessingNotFound, EntityNotFound, CandidateNotFound)):
            return HTTPException(404, "Processing source or job not found.")
        if isinstance(error, ProcessingConflict):
            return HTTPException(409, "Processing request conflicts.")
        if isinstance(error, (EntitySourceError, CandidateSourceError, ValueError)):
            return HTTPException(422, "Processing source is invalid.")
        return HTTPException(503, "Processing is unavailable.")

    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 422, 500, 503)
    }

    def envelope(request: Request, job: ProcessingJob) -> ProcessingEnvelope:
        meta = response_meta(request)
        return ProcessingEnvelope(
            data=job,
            meta=meta.model_copy(
                update={
                    "versions": meta.versions.model_copy(
                        update={"parse_version_id": job.request.parse_version_id}
                    )
                }
            ),
        )

    @router.post("/jobs", response_model=ProcessingEnvelope, responses=errors)
    def submit(
        request: Request,
        body: ProcessingRequest,
        user: Annotated[User, Depends(admin)],
        processor: Annotated[ProcessingService, Depends(configured)],
    ) -> ProcessingEnvelope:
        try:
            job = processor.repository.submit(body, user)
            processor.repository.dispatch(processor.send, job_id=job.id, user=user)
        except failures as error:
            raise mapped(error) from None
        return envelope(request, job)

    @router.get("/jobs/{job_id}", response_model=ProcessingEnvelope, responses=errors)
    def get_job(
        request: Request,
        job_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        processor: Annotated[ProcessingService, Depends(configured)],
    ) -> ProcessingEnvelope:
        try:
            job = processor.repository.get(job_id)
            if job is None:
                raise ProcessingNotFound()
        except failures as error:
            raise mapped(error) from None
        return envelope(request, job)

    @router.post("/jobs/{job_id}/dispatch", response_model=DispatchEnvelope, responses=errors)
    def dispatch(
        request: Request,
        job_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        processor: Annotated[ProcessingService, Depends(configured)],
    ) -> DispatchEnvelope:
        try:
            if processor.repository.get(job_id) is None:
                raise ProcessingNotFound()
            count = processor.repository.dispatch(processor.send, job_id=job_id, user=user)
        except failures as error:
            raise mapped(error) from None
        return DispatchEnvelope(
            data=DispatchReceipt(dispatched=count == 1), meta=response_meta(request)
        )

    return router
