"""Authenticated read-only retrieval and extractive answer endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope, SuccessEnvelope
from regintel.reads.api import perform
from regintel.retrieval.models import AnswerResult, RetrievalRequest, RetrievalResult
from regintel.retrieval.service import InvalidQuery, RetrievalService


def create_retrieval_router(
    auth: AuthService | None,
    service: RetrievalService | None,
) -> APIRouter:
    router = APIRouter(tags=["published retrieval and exact source answers"])
    reader = user_dependency(auth)
    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (400, 401, 403, 404, 422, 500, 503)
    }

    def configured() -> RetrievalService:
        if service is None:
            raise HTTPException(503, "Published retrieval is unavailable.")
        return service

    def selected_meta(request: Request, result: RetrievalResult) -> None:
        meta = response_meta(request)
        request.state.contract_meta = meta.model_copy(
            update={
                "versions": meta.versions.model_copy(
                    update={"corpus_version_id": result.view.corpus_version_id}
                )
            }
        )

    @router.post("/v1/retrieval", response_model=SuccessEnvelope[RetrievalResult], responses=errors)
    def retrieve(
        body: RetrievalRequest,
        request: Request,
        user: Annotated[User, Depends(reader)],
        retrieval: Annotated[RetrievalService, Depends(configured)],
    ) -> SuccessEnvelope[RetrievalResult]:
        try:
            result = perform(lambda: retrieval.search(body))
        except InvalidQuery:
            raise HTTPException(422, "Encoded question exceeds the 512-token limit.") from None
        selected_meta(request, result)
        return SuccessEnvelope(data=result, meta=response_meta(request))

    @router.post("/v1/answers", response_model=SuccessEnvelope[AnswerResult], responses=errors)
    def answer(
        body: RetrievalRequest,
        request: Request,
        user: Annotated[User, Depends(reader)],
        retrieval: Annotated[RetrievalService, Depends(configured)],
    ) -> SuccessEnvelope[AnswerResult]:
        try:
            result = perform(lambda: retrieval.answer(body))
        except InvalidQuery:
            raise HTTPException(422, "Encoded question exceeds the 512-token limit.") from None
        selected_meta(request, result.retrieval)
        return SuccessEnvelope(data=result, meta=response_meta(request))

    return router
