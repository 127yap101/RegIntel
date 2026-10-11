"""Admin-only streamed uploads and authoritative status, before any source access."""

from collections.abc import Callable
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope
from regintel.contracts.primitives import CanonicalId
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.jobs import FilingJob, FilingJobEnvelope, UploadMetadata
from regintel.ingestion.repository import JobRepository
from regintel.ingestion.storage import SourceStorage, UploadError


class IngestionService:
    def __init__(
        self, settings: IngestionSettings, repository: JobRepository, sender: Callable[[str], None]
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.sender = sender
        self.storage = SourceStorage(settings)


def create_ingestion_router(
    auth: AuthService | None, service: IngestionService | None
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["filing ingestion"])
    admin = user_dependency(auth, admin=True)

    def configured() -> IngestionService:
        if service is None:
            raise HTTPException(503, "Ingestion is unavailable.")
        return service

    def envelope(request: Request, job: FilingJob) -> FilingJobEnvelope:
        meta = response_meta(request)
        return FilingJobEnvelope(
            data=job,
            meta=meta.model_copy(
                update={
                    "versions": meta.versions.model_copy(
                        update={
                            "filing_version_id": job.filing_version_id,
                            "parse_version_id": job.parse_version_id,
                        }
                    )
                }
            ),
        )

    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope}
        for code in (400, 401, 403, 404, 409, 413, 415, 422, 500, 503)
    }

    @router.post(
        "/filings",
        status_code=202,
        response_model=FilingJobEnvelope,
        responses=errors,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def upload(
        request: Request,
        user: Annotated[User, Depends(admin)],
        ingestion: Annotated[IngestionService, Depends(configured)],
        metadata: Annotated[UploadMetadata, Query()],
    ) -> FilingJobEnvelope:
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/pdf":
            raise HTTPException(415, "PDF content required.")
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdecimal():
                raise HTTPException(400, "Invalid content length.")
            if len(length) > 12 or int(length) > ingestion.settings.max_bytes:
                raise HTTPException(413, "Upload limit exceeded.")
        try:
            stage = ingestion.storage.stage()
        except (UploadError, OSError):
            raise HTTPException(503, "Ingestion is unavailable.") from None
        try:
            async for chunk in request.stream():
                await run_in_threadpool(stage.write, chunk)
            source = await run_in_threadpool(stage.finish)
            job = await run_in_threadpool(
                ingestion.repository.submit,
                source,
                metadata,
                ingestion.settings.configuration_sha256,
                user.id,
                user.auth_version,
            )
            # Submission is committed before Redis I/O. Dispatch failure remains in
            # PostgreSQL and cannot turn a durable upload into a fabricated failure.
            try:
                await run_in_threadpool(
                    ingestion.repository.dispatch, ingestion.sender, limit=1, job_id=job.id
                )
            except (psycopg.Error, OSError):
                pass
            return envelope(request, job)
        except UploadError as error:
            raise HTTPException(
                error.status,
                error.code,
                headers={"WWW-Authenticate": "Bearer"} if error.status == 401 else None,
            ) from None
        except (psycopg.Error, OSError):
            raise HTTPException(503, "Ingestion is unavailable.") from None
        finally:
            await run_in_threadpool(stage.close)

    @router.get("/filing-jobs/{job_id}", response_model=FilingJobEnvelope, responses=errors)
    def status(
        request: Request,
        job_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        ingestion: Annotated[IngestionService, Depends(configured)],
    ) -> FilingJobEnvelope:
        try:
            job = ingestion.repository.get(job_id)
        except (psycopg.Error, OSError):
            raise HTTPException(503, "Ingestion is unavailable.") from None
        if job is None:
            raise HTTPException(404, "Job not found.")
        return envelope(request, job)

    return router
