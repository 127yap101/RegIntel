"""Authenticated M3 draft/review/publication, glossary and extractive context endpoints."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId
from regintel.learning.draft_pack import LearningStarterPack
from regintel.learning.models import (
    DefinitionDraft,
    DefinitionQueue,
    DraftFilter,
    GlossaryHistory,
    GlossaryVersion,
    LearningOverview,
    LearningReview,
    PublishLearning,
    ReviewedDefinition,
    StoredDefinition,
)
from regintel.learning.repository import (
    LearningConflict,
    LearningForbidden,
    LearningNotFound,
    LearningUnavailable,
)
from regintel.learning.service import LearningContextRequest, LearningExplanation, LearningService
from regintel.reads.repository import ReadNotFound, ReadUnavailable


def perform[T](work: Callable[[], T]) -> T:
    try:
        return work()
    except LearningForbidden:
        raise HTTPException(403, "Learning access is unavailable.") from None
    except (LearningNotFound, ReadNotFound):
        raise HTTPException(404, "Selected learning content is unavailable.") from None
    except LearningConflict:
        raise HTTPException(409, "Learning review or source context conflicts.") from None
    except (LearningUnavailable, ReadUnavailable):
        raise HTTPException(503, "Reviewed learning is unavailable.") from None


def create_learning_router(auth: AuthService | None, service: LearningService | None) -> APIRouter:
    router = APIRouter(tags=["M3 financial learning"])
    reader, administrator = user_dependency(auth), user_dependency(auth, admin=True)
    errors: dict[int | str, dict[str, object]] = {
        status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409, 422, 503)
    }

    def ready() -> LearningService:
        if service is None:
            raise HTTPException(503, "Reviewed learning storage is unavailable.")
        return service

    def envelope[T](
        data: T, request: Request, version: str | None = None, corpus: str | None = None
    ) -> SuccessEnvelope[T]:
        meta = response_meta(request)
        meta = meta.model_copy(
            update={
                "versions": meta.versions.model_copy(
                    update={"glossary_version_id": version, "corpus_version_id": corpus}
                )
            }
        )
        return SuccessEnvelope(data=data, meta=meta)

    @router.get(
        "/v1/learning/status", response_model=SuccessEnvelope[LearningOverview], responses=errors
    )
    def status(
        request: Request, user: Annotated[User, Depends(reader)]
    ) -> SuccessEnvelope[LearningOverview]:
        data = perform(lambda: ready().repository.overview(user))
        return envelope(data, request, data.glossary_version_id)

    @router.get(
        "/v1/learning/glossary/{version_id}",
        response_model=SuccessEnvelope[GlossaryVersion],
        responses=errors,
    )
    def glossary(
        version_id: CanonicalId, request: Request, user: Annotated[User, Depends(reader)]
    ) -> SuccessEnvelope[GlossaryVersion]:
        data = perform(lambda: ready().repository.glossary(version_id, user))
        return envelope(data, request, data.glossary_version_id)

    @router.get(
        "/v1/learning/starter-pack",
        response_model=SuccessEnvelope[LearningStarterPack],
        responses=errors,
    )
    def starter_pack(
        request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[LearningStarterPack]:
        return envelope(perform(lambda: ready().repository.starter_pack(user)), request)

    @router.get(
        "/v1/learning/versions", response_model=SuccessEnvelope[GlossaryHistory], responses=errors
    )
    def history(
        request: Request,
        user: Annotated[User, Depends(reader)],
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
        limit: Annotated[int, Query(ge=1, le=20)] = 20,
    ) -> SuccessEnvelope[GlossaryHistory]:
        return envelope(
            perform(lambda: ready().repository.history(user, offset=offset, limit=limit)), request
        )

    @router.get(
        "/v1/learning/drafts", response_model=SuccessEnvelope[DefinitionQueue], responses=errors
    )
    def queue(
        request: Request,
        user: Annotated[User, Depends(administrator)],
        state: DraftFilter = "PENDING_REVIEW",
        q: Annotated[str, Query(max_length=120)] = "",
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
        limit: Annotated[int, Query(ge=1, le=20)] = 20,
    ) -> SuccessEnvelope[DefinitionQueue]:
        return envelope(
            perform(
                lambda: ready().repository.queue(
                    user, state=state, query=q, offset=offset, limit=limit
                )
            ),
            request,
        )

    @router.post(
        "/v1/learning/drafts", response_model=SuccessEnvelope[StoredDefinition], responses=errors
    )
    def propose(
        body: DefinitionDraft, request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[StoredDefinition]:
        return envelope(perform(lambda: ready().repository.propose(body, user)), request)

    @router.get(
        "/v1/learning/drafts/{definition_id}",
        response_model=SuccessEnvelope[StoredDefinition],
        responses=errors,
    )
    def draft(
        definition_id: CanonicalId, request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[StoredDefinition]:
        return envelope(perform(lambda: ready().repository.draft(definition_id, user)), request)

    @router.get(
        "/v1/learning/drafts/{definition_id}/review",
        response_model=SuccessEnvelope[ReviewedDefinition],
        responses=errors,
    )
    def recorded_review(
        definition_id: CanonicalId, request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[ReviewedDefinition]:
        return envelope(perform(lambda: ready().repository.reviewed(definition_id, user)), request)

    @router.post(
        "/v1/learning/drafts/{definition_id}/review",
        response_model=SuccessEnvelope[ReviewedDefinition],
        responses=errors,
    )
    def review(
        definition_id: CanonicalId,
        body: LearningReview,
        request: Request,
        user: Annotated[User, Depends(administrator)],
    ) -> SuccessEnvelope[ReviewedDefinition]:
        return envelope(
            perform(lambda: ready().repository.review(definition_id, body, user)), request
        )

    @router.post(
        "/v1/learning/versions", response_model=SuccessEnvelope[GlossaryVersion], responses=errors
    )
    def publish(
        body: PublishLearning, request: Request, user: Annotated[User, Depends(administrator)]
    ) -> SuccessEnvelope[GlossaryVersion]:
        data = perform(lambda: ready().repository.publish(body, user))
        return envelope(data, request, data.glossary_version_id)

    @router.post(
        "/v1/learning/context",
        response_model=SuccessEnvelope[LearningExplanation],
        responses=errors,
    )
    def explain(
        body: LearningContextRequest, request: Request, user: Annotated[User, Depends(reader)]
    ) -> SuccessEnvelope[LearningExplanation]:
        data = perform(lambda: ready().explain(body, user))
        return envelope(data, request, data.glossary_version_id, data.view.corpus_version_id)

    return router
