"""Authenticated administrator navigation; mutations stay in their original APIs."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from regintel.admin.models import MetricPage, QueueKind, QueuePage, ReviewFilter, ReviewPage
from regintel.admin.repository import AdminRepository
from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.candidates.repository import CandidateSourceError, CandidateUnavailable
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId
from regintel.validation.repository import (
    ValidationAuthorizationError,
    ValidationNotFound,
    ValidationSourceError,
    ValidationUnavailable,
)


def create_admin_router(auth: AuthService | None, repository: AdminRepository | None) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/workspace", tags=["administrator workspace"])
    admin = user_dependency(auth, admin=True)

    def configured() -> AdminRepository:
        if repository is None:
            raise HTTPException(503, "Administrator workspace is unavailable.")
        return repository

    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (401, 403, 404, 422, 503)
    }
    failures = (
        ValidationAuthorizationError,
        ValidationNotFound,
        ValidationSourceError,
        ValidationUnavailable,
        CandidateSourceError,
        CandidateUnavailable,
        ValueError,
        psycopg.Error,
        OSError,
    )

    def mapped(error: Exception) -> HTTPException:
        if isinstance(error, ValidationAuthorizationError):
            return HTTPException(403, "Current administrator access is required.")
        if isinstance(error, ValidationNotFound):
            return HTTPException(404, "Validation audit not found.")
        return HTTPException(503, "Administrator workspace could not be verified.")

    @router.get("/queues/{kind}", response_model=SuccessEnvelope[QueuePage], responses=errors)
    def queue(
        request: Request,
        kind: QueueKind,
        user: Annotated[User, Depends(admin)],
        store: Annotated[AdminRepository, Depends(configured)],
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
        limit: Annotated[int, Query(ge=1, le=25)] = 20,
    ) -> SuccessEnvelope[QueuePage]:
        try:
            data = store.queue(kind, offset, limit, user)
        except failures as error:
            raise mapped(error) from None
        return SuccessEnvelope(data=data, meta=response_meta(request))

    @router.get("/reviews/{run_id}", response_model=SuccessEnvelope[ReviewPage], responses=errors)
    def review_page(
        request: Request,
        run_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        store: Annotated[AdminRepository, Depends(configured)],
        state: ReviewFilter = "ALL",
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
        limit: Annotated[int, Query(ge=1, le=25)] = 20,
    ) -> SuccessEnvelope[ReviewPage]:
        try:
            data = store.review_page(run_id, state, offset, limit, user)
        except failures as error:
            raise mapped(error) from None
        meta = response_meta(request)
        return SuccessEnvelope(
            data=data,
            meta=meta.model_copy(
                update={
                    "versions": meta.versions.model_copy(
                        update={"parse_version_id": data.parse_version_id}
                    )
                }
            ),
        )

    @router.get("/metrics", response_model=SuccessEnvelope[MetricPage], responses=errors)
    def metrics(
        request: Request,
        user: Annotated[User, Depends(admin)],
        store: Annotated[AdminRepository, Depends(configured)],
    ) -> SuccessEnvelope[MetricPage]:
        try:
            data = store.metrics(user)
        except failures as error:
            raise mapped(error) from None
        return SuccessEnvelope(data=data, meta=response_meta(request))

    return router
