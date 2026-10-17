"""M2-owned authenticated comparison and explicit quote availability contracts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from regintel.analysis.models import (
    QUOTES_UNAVAILABLE,
    ComparisonRequest,
    ComparisonResult,
    QuotesResult,
)
from regintel.analysis.service import ComparisonService
from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope, SuccessEnvelope
from regintel.reads.api import perform
from regintel.reads.service import PublishedReadService


def create_analysis_router(
    auth: AuthService | None, reads: PublishedReadService | None
) -> APIRouter:
    router = APIRouter(tags=["M2 analysis and comparison"])
    reader = user_dependency(auth)
    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (401, 403, 404, 422, 500, 503)
    }

    @router.post("/v1/compare", response_model=SuccessEnvelope[ComparisonResult], responses=errors)
    def compare(
        body: ComparisonRequest,
        request: Request,
        user: Annotated[User, Depends(reader)],
    ) -> SuccessEnvelope[ComparisonResult]:
        if reads is None:
            raise HTTPException(503, "Published comparison inputs are unavailable.")
        result = perform(lambda: ComparisonService(reads).compare(body))
        meta = response_meta(request)
        meta = meta.model_copy(
            update={
                "versions": meta.versions.model_copy(
                    update={"corpus_version_id": result.view.corpus_version_id}
                )
            }
        )
        return SuccessEnvelope(data=result, meta=meta)

    @router.get("/v1/quotes", response_model=SuccessEnvelope[QuotesResult], responses=errors)
    def quotes(
        request: Request,
        user: Annotated[User, Depends(reader)],
    ) -> SuccessEnvelope[QuotesResult]:
        return SuccessEnvelope(data=QUOTES_UNAVAILABLE, meta=response_meta(request))

    return router
