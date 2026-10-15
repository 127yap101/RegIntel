"""Authenticated, version-bound M1 consumer endpoints; no publication writes."""

from collections.abc import Callable
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId, DateString
from regintel.evidence.http import source_response
from regintel.evidence.source import read_verified_source
from regintel.ingestion.storage import UploadError
from regintel.publication.graph import GraphUnavailable
from regintel.reads.models import CompanyGraph, CompanyPage, FactPage, PublishedEvidence, ViewInfo
from regintel.reads.repository import ReadNotFound
from regintel.reads.service import PublishedReadService, ReadScope


def perform[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ReadNotFound:
        raise HTTPException(404, "Published resource not found.") from None
    except (ValueError, OSError, psycopg.Error, GraphUnavailable, UploadError):
        raise HTTPException(503, "Published resource is unavailable.") from None


def create_read_router(auth: AuthService | None, service: PublishedReadService | None) -> APIRouter:
    router = APIRouter(tags=["published company intelligence"])
    reader = user_dependency(auth)
    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (400, 401, 403, 404, 416, 422, 500, 503)
    }

    def configured() -> PublishedReadService:
        if service is None:
            raise HTTPException(503, "Published reads are unavailable.")
        return service

    def selected(
        request: Request,
        publisher: PublishedReadService,
        corpus_id: str | None,
        as_of_date: str | None,
        historical: bool,
    ) -> ReadScope:
        scope = perform(lambda: publisher.scope(corpus_id, as_of_date, historical))
        meta = response_meta(request)
        request.state.contract_meta = meta.model_copy(
            update={
                "versions": meta.versions.model_copy(
                    update={"corpus_version_id": scope.manifest.id}
                )
            }
        )
        return scope

    @router.get("/v1/published-corpus", response_model=SuccessEnvelope[ViewInfo], responses=errors)
    def current(
        request: Request,
        user: Annotated[User, Depends(reader)],
        publisher: Annotated[PublishedReadService, Depends(configured)],
        corpus_version_id: CanonicalId | None = None,
        as_of_date: DateString | None = None,
        historical: bool = False,
    ) -> SuccessEnvelope[ViewInfo]:
        scope = selected(request, publisher, corpus_version_id, as_of_date, historical)
        return SuccessEnvelope(data=scope.info, meta=response_meta(request))

    @router.get("/v1/companies", response_model=SuccessEnvelope[CompanyPage], responses=errors)
    def companies(
        request: Request,
        user: Annotated[User, Depends(reader)],
        publisher: Annotated[PublishedReadService, Depends(configured)],
        q: Annotated[str, Query(max_length=120)] = "",
        corpus_version_id: CanonicalId | None = None,
        as_of_date: DateString | None = None,
        historical: bool = False,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> SuccessEnvelope[CompanyPage]:
        scope = selected(request, publisher, corpus_version_id, as_of_date, historical)
        result = perform(lambda: publisher.companies(scope, q, offset, limit))
        return SuccessEnvelope(data=result, meta=response_meta(request))

    @router.get(
        "/v1/companies/{company_id}/facts",
        response_model=SuccessEnvelope[FactPage],
        responses=errors,
    )
    def facts(
        request: Request,
        company_id: CanonicalId,
        user: Annotated[User, Depends(reader)],
        publisher: Annotated[PublishedReadService, Depends(configured)],
        corpus_version_id: CanonicalId | None = None,
        as_of_date: DateString | None = None,
        historical: bool = False,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> SuccessEnvelope[FactPage]:
        scope = selected(request, publisher, corpus_version_id, as_of_date, historical)
        result = perform(lambda: publisher.facts(scope, company_id, offset, limit))
        return SuccessEnvelope(data=result, meta=response_meta(request))

    @router.get(
        "/v1/companies/{company_id}/graph",
        response_model=SuccessEnvelope[CompanyGraph],
        responses=errors,
        description=(
            "Direct published relations only. More than 1000 relations returns 503; "
            "results are never silently truncated."
        ),
    )
    def graph(
        request: Request,
        company_id: CanonicalId,
        user: Annotated[User, Depends(reader)],
        publisher: Annotated[PublishedReadService, Depends(configured)],
        corpus_version_id: CanonicalId | None = None,
        as_of_date: DateString | None = None,
        historical: bool = False,
    ) -> SuccessEnvelope[CompanyGraph]:
        scope = selected(request, publisher, corpus_version_id, as_of_date, historical)
        result = perform(lambda: publisher.company_graph(scope, company_id))
        return SuccessEnvelope(data=result, meta=response_meta(request))

    @router.get(
        "/v1/corpora/{corpus_id}/observations/{observation_id}/evidence/{evidence_id}",
        response_model=SuccessEnvelope[PublishedEvidence],
        responses=errors,
    )
    def evidence(
        request: Request,
        corpus_id: CanonicalId,
        observation_id: CanonicalId,
        evidence_id: CanonicalId,
        user: Annotated[User, Depends(reader)],
        publisher: Annotated[PublishedReadService, Depends(configured)],
        as_of_date: DateString | None = None,
        historical: bool = False,
    ) -> SuccessEnvelope[PublishedEvidence]:
        scope = selected(request, publisher, corpus_id, as_of_date, historical)
        result = perform(lambda: publisher.published_evidence(scope, observation_id, evidence_id))
        meta = response_meta(request)
        meta = meta.model_copy(
            update={
                "versions": meta.versions.model_copy(
                    update={
                        "filing_version_id": result.evidence.record.source.filing_version_id,
                        "parse_version_id": result.evidence.record.source.parse_version_id,
                    }
                )
            }
        )
        return SuccessEnvelope(data=result, meta=meta)

    source_responses: dict[int | str, dict[str, object]] = {
        **errors,
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}},
        206: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}},
        304: {"description": "Current authenticated published source has a matching entity tag."},
    }

    @router.get(
        "/v1/corpora/{corpus_id}/observations/{observation_id}/source.pdf",
        response_class=Response,
        responses=source_responses,
    )
    @router.head(
        "/v1/corpora/{corpus_id}/observations/{observation_id}/source.pdf",
        response_class=Response,
        responses=source_responses,
    )
    def source(
        request: Request,
        corpus_id: CanonicalId,
        observation_id: CanonicalId,
        user: Annotated[User, Depends(reader)],
        publisher: Annotated[PublishedReadService, Depends(configured)],
        as_of_date: DateString | None = None,
        historical: bool = False,
    ) -> Response:
        scope = selected(request, publisher, corpus_id, as_of_date, historical)
        blob = perform(lambda: publisher.source(scope, observation_id))
        data = perform(lambda: read_verified_source(publisher.evidence.storage, blob))
        return source_response(request, data, blob.sha256, corpus_id=scope.manifest.id)

    return router
