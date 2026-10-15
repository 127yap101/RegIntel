"""Explicit administrator publication and authenticated version-bound corpus views."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId, DateString
from regintel.publication.engine import PublicationConflict, corpus_view
from regintel.publication.graph import GraphUnavailable
from regintel.publication.models import CorpusManifest, CorpusView, PublicationRequest
from regintel.publication.service import PublicationService
from regintel.validation.repository import ValidationAuthorizationError


def create_publication_router(
    auth: AuthService | None, service: PublicationService | None
) -> APIRouter:
    router = APIRouter(tags=["corpus publication"])
    admin = user_dependency(auth, admin=True)
    reader = user_dependency(auth)
    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (401, 403, 409, 422, 500, 503)
    }

    def configured() -> PublicationService:
        if service is None:
            raise HTTPException(503, "Corpus publication is unavailable.")
        return service

    def mapped(error: Exception) -> HTTPException:
        if isinstance(error, ValidationAuthorizationError):
            return HTTPException(403, "Current administrator approval is required.")
        if isinstance(error, GraphUnavailable):
            return HTTPException(503, "Corpus publication is unavailable.")
        if isinstance(error, PublicationConflict):
            return HTTPException(409, "Publication conflicts with approved or published state.")
        if isinstance(error, ValueError):
            return HTTPException(422, "Publication source or support is invalid.")
        return HTTPException(503, "Corpus publication is unavailable.")

    @router.post(
        "/v1/admin/publication/builds",
        response_model=SuccessEnvelope[CorpusManifest],
        responses=errors,
    )
    def build(
        request: Request,
        body: PublicationRequest,
        user: Annotated[User, Depends(admin)],
        publisher: Annotated[PublicationService, Depends(configured)],
    ) -> SuccessEnvelope[CorpusManifest]:
        try:
            manifest = publisher.build(body, user)
        except (ValueError, OSError, psycopg.Error, GraphUnavailable) as error:
            raise mapped(error) from None
        return SuccessEnvelope(data=manifest, meta=response_meta(request))

    @router.get(
        "/v1/admin/publication/builds/{corpus_id}",
        response_model=SuccessEnvelope[CorpusManifest],
        responses=errors,
    )
    def get_build(
        request: Request,
        corpus_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        publisher: Annotated[PublicationService, Depends(configured)],
    ) -> SuccessEnvelope[CorpusManifest]:
        try:
            manifest = publisher.repository.get_build(corpus_id, user)
        except (ValueError, OSError, psycopg.Error, GraphUnavailable) as error:
            raise mapped(error) from None
        return SuccessEnvelope(data=manifest, meta=response_meta(request))

    @router.post(
        "/v1/admin/publication/builds/{corpus_id}/publish",
        response_model=SuccessEnvelope[CorpusManifest],
        responses=errors,
    )
    def publish(
        request: Request,
        corpus_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        publisher: Annotated[PublicationService, Depends(configured)],
    ) -> SuccessEnvelope[CorpusManifest]:
        try:
            manifest = publisher.publish(corpus_id, user)
        except (ValueError, OSError, psycopg.Error, GraphUnavailable) as error:
            raise mapped(error) from None
        return SuccessEnvelope(data=manifest, meta=response_meta(request))

    @router.get(
        "/v1/corpora/{corpus_id}", response_model=SuccessEnvelope[CorpusView], responses=errors
    )
    def view(
        request: Request,
        corpus_id: CanonicalId,
        user: Annotated[User, Depends(reader)],
        publisher: Annotated[PublicationService, Depends(configured)],
        as_of_date: DateString | None = None,
        historical: bool = False,
    ) -> SuccessEnvelope[CorpusView]:
        try:
            manifest = publisher.repository.published(corpus_id)
            result = corpus_view(manifest, as_of_date, historical=historical)
        except (ValueError, OSError, psycopg.Error, GraphUnavailable) as error:
            raise mapped(error) from None
        meta = response_meta(request)
        return SuccessEnvelope(
            data=result,
            meta=meta.model_copy(
                update={
                    "versions": meta.versions.model_copy(update={"corpus_version_id": manifest.id})
                }
            ),
        )

    @router.post(
        "/v1/admin/publication/builds/{corpus_id}/rebuild",
        response_model=SuccessEnvelope[CorpusManifest],
        responses=errors,
    )
    def rebuild(
        request: Request,
        corpus_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        publisher: Annotated[PublicationService, Depends(configured)],
    ) -> SuccessEnvelope[CorpusManifest]:
        try:
            manifest = publisher.rebuild(corpus_id, user)
        except (ValueError, OSError, psycopg.Error, GraphUnavailable) as error:
            raise mapped(error) from None
        return SuccessEnvelope(data=manifest, meta=response_meta(request))

    return router
