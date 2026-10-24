"""Explicit JSON envelopes; OAuth2, health and stream protocols keep their shape."""

from collections.abc import Mapping
from typing import cast
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from regintel.contracts.models import (
    CONTRACT_VERSION,
    ApiError,
    ErrorDetail,
    ErrorEnvelope,
    ResponseMeta,
    VersionContext,
)

_ERRORS: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "Invalid request."),
    401: ("UNAUTHENTICATED", "Invalid bearer token."),
    403: ("FORBIDDEN", "Administrator role required."),
    404: ("NOT_FOUND", "Resource not found."),
    405: ("METHOD_NOT_ALLOWED", "Method not allowed."),
    409: ("CONFLICT", "Conflicting filing metadata or source identity."),
    413: ("PAYLOAD_TOO_LARGE", "Upload limit exceeded."),
    415: ("UNSUPPORTED_MEDIA_TYPE", "PDF content required."),
    422: ("VALIDATION_ERROR", "Invalid request."),
    500: ("INTERNAL_ERROR", "Internal server error."),
    503: ("SERVICE_UNAVAILABLE", "Authentication is unavailable."),
}


def new_response_meta() -> ResponseMeta:
    return ResponseMeta(
        request_id=str(uuid4()),
        contract_version=CONTRACT_VERSION,
        versions=VersionContext(
            corpus_version_id=None,
            filing_version_id=None,
            parse_version_id=None,
            glossary_version_id=None,
            quote_version_id=None,
            portfolio_version_id=None,
        ),
    )


def response_meta(request: Request) -> ResponseMeta:
    return cast(ResponseMeta, request.state.contract_meta)


def uses_json_envelope(request: Request) -> bool:
    return request.url.path.startswith("/v1/") and request.url.path != "/v1/auth/token"


def error_response(
    request: Request,
    status: int,
    *,
    details: list[ErrorDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    code, message = _ERRORS.get(status, ("HTTP_ERROR", "Request failed."))
    if status == 409 and request.url.path.startswith(("/v1/learning/", "/v1/portfolio/")):
        message = "Conflicting request or version."
    if status == 503 and not request.url.path.startswith("/v1/auth/"):
        message = "Service is unavailable."
    envelope = ErrorEnvelope(
        error=ApiError(
            code=code, message=message, details=tuple(details) if details is not None else ()
        ),
        meta=response_meta(request),
    )
    return JSONResponse(
        status_code=status, content=envelope.model_dump(mode="json"), headers=headers
    )
