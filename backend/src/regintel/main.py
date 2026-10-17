"""FastAPI application factory with independent liveness and optional explicit auth."""

from collections.abc import Awaitable, Callable
from typing import Literal, cast

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from regintel import __version__
from regintel.admin.api import create_admin_router
from regintel.admin.repository import AdminRepository
from regintel.analysis.api import create_analysis_router
from regintel.auth.api import create_auth_router
from regintel.auth.service import AuthService
from regintel.candidates.api import CandidateService, create_candidate_router
from regintel.config import Environment, Settings
from regintel.contracts.http import error_response, new_response_meta, uses_json_envelope
from regintel.contracts.models import ErrorDetail
from regintel.entities.api import EntityService, create_entity_router
from regintel.evidence.api import EvidenceService, create_evidence_router
from regintel.ingestion.api import IngestionService, create_ingestion_router
from regintel.processing.api import ProcessingService, create_processing_router
from regintel.publication.api import create_publication_router
from regintel.publication.service import PublicationService
from regintel.reads.api import create_read_router
from regintel.reads.service import PublishedReadService
from regintel.retrieval.api import create_retrieval_router
from regintel.retrieval.service import RetrievalService
from regintel.validation.api import ValidationService, create_validation_router

type ErrorLocation = Literal["body", "query", "path", "header", "cookie", "request"]


class LivenessResponse(BaseModel):
    """Process liveness does not imply database or extraction readiness."""

    status: Literal["ok"] = "ok"
    service: Literal["RegIntel Finance"] = "RegIntel Finance"
    environment: Environment


def create_app(
    settings: Settings | None = None,
    *,
    auth_service: AuthService | None = None,
    ingestion_service: IngestionService | None = None,
    evidence_service: EvidenceService | None = None,
    entity_service: EntityService | None = None,
    candidate_service: CandidateService | None = None,
    validation_service: ValidationService | None = None,
    processing_service: ProcessingService | None = None,
    publication_service: PublicationService | None = None,
    read_service: PublishedReadService | None = None,
    retrieval_service: RetrievalService | None = None,
    admin_repository: AdminRepository | None = None,
) -> FastAPI:
    """Construct isolated applications for tests and native development."""

    configuration = settings if settings is not None else Settings()
    application = FastAPI(
        title="RegIntel Finance API",
        version=__version__,
        description="Evidence-grounded regulatory filing and financial learning platform.",
    )

    @application.middleware("http")
    async def sanitize_unhandled_errors(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception:
            # Never echo exception text or submitted filing/authentication data.
            return (
                error_response(request, 500)
                if uses_json_envelope(request)
                else JSONResponse(status_code=500, content={"detail": "Internal server error."})
            )

    @application.exception_handler(RequestValidationError)
    async def sanitize_validation(request: Request, error: RequestValidationError) -> Response:
        if uses_json_envelope(request):
            locations: set[ErrorLocation] = set()
            for item in error.errors():
                location = item.get("loc", ("request",))[0]
                locations.add(
                    cast(ErrorLocation, location)
                    if isinstance(location, str)
                    and location in {"body", "query", "path", "header", "cookie"}
                    else "request"
                )
            details = [
                ErrorDetail(location=location, code="INVALID_VALUE")
                for location in sorted(locations)
            ]
            return error_response(request, 422, details=details)
        if request.url.path.startswith("/v1/auth/"):
            return JSONResponse(
                status_code=422, content={"detail": "Invalid authentication request."}
            )
        return await request_validation_exception_handler(request, error)

    @application.exception_handler(StarletteHTTPException)
    async def sanitize_http_error(request: Request, error: StarletteHTTPException) -> Response:
        if uses_json_envelope(request):
            return error_response(request, error.status_code, headers=error.headers)
        return await http_exception_handler(request, error)

    # CORS also covers responses produced by the sanitizing middleware.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configuration.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "HEAD", "POST"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "Range",
            "If-Range",
            "If-None-Match",
        ],
        expose_headers=[
            "X-Request-ID",
            "ETag",
            "Content-Range",
            "Accept-Ranges",
            "Content-Length",
            "X-Corpus-Version-ID",
        ],
    )

    # Context and response headers also cover preflights that CORS handles directly.
    @application.middleware("http")
    async def request_contract_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        meta = new_response_meta()
        request.state.contract_meta = meta
        response = await call_next(request)
        response.headers["X-Request-ID"] = meta.request_id
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    application.include_router(create_auth_router(auth_service))
    application.include_router(create_ingestion_router(auth_service, ingestion_service))
    application.include_router(create_evidence_router(auth_service, evidence_service))
    application.include_router(create_entity_router(auth_service, entity_service))
    application.include_router(create_candidate_router(auth_service, candidate_service))
    application.include_router(create_validation_router(auth_service, validation_service))
    application.include_router(create_processing_router(auth_service, processing_service))
    application.include_router(create_publication_router(auth_service, publication_service))
    application.include_router(create_read_router(auth_service, read_service))
    application.include_router(create_analysis_router(auth_service, read_service))
    application.include_router(create_retrieval_router(auth_service, retrieval_service))
    application.include_router(create_admin_router(auth_service, admin_repository))

    @application.get("/health/live", response_model=LivenessResponse, tags=["health"])
    def liveness() -> LivenessResponse:
        return LivenessResponse(environment=configuration.environment)

    return application


app = create_app()
