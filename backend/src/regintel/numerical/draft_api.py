"""Private computation of an unpublished draft; no publication or projection writes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope, SuccessEnvelope
from regintel.numerical.draft_models import (
    NumericalPublicationDraft,
    NumericalPublicationDraftRequest,
)
from regintel.numerical.draft_repository import NumericalPublicationDraftRepository
from regintel.numerical.repository import NumericalRepository
from regintel.numerical.review_api import perform


def create_numerical_draft_router(
    auth: AuthService | None, source: NumericalRepository | None
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/admin/numerical/publication-drafts", tags=["numerical publication drafts"]
    )
    administrator = user_dependency(auth, admin=True)
    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 422, 503)
    }

    @router.post("", response_model=SuccessEnvelope[NumericalPublicationDraft], responses=errors)
    def prepare(
        body: NumericalPublicationDraftRequest,
        request: Request,
        user: Annotated[User, Depends(administrator)],
    ) -> SuccessEnvelope[NumericalPublicationDraft]:
        if source is None:
            raise HTTPException(503, "Numerical publication draft prerequisites are unavailable.")
        return SuccessEnvelope(
            data=perform(lambda: NumericalPublicationDraftRepository(source).prepare(body, user)),
            meta=response_meta(request),
        )

    return router
