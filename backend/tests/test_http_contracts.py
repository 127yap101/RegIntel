"""Exercise actual FastAPI envelope/status/header/sanitization boundaries."""

from uuid import UUID

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, SecretStr

from regintel.auth.config import AuthSettings
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.config import Settings
from regintel.contracts.models import ErrorEnvelope, ResponseMeta
from regintel.main import create_app


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    count: int


class EmptyRepository:
    def get_by_username(self, username: str) -> User | None:
        return None

    def get_by_id(self, user_id: UUID) -> User | None:
        return None


def test_enveloped_errors_have_fresh_server_identity_and_preserve_http_headers() -> None:
    application = create_app(Settings(environment="test"))
    with TestClient(application) as client:
        first = client.get("/v1/auth/me", headers={"X-Request-ID": "untrusted-caller-id"})
        second = client.get("/v1/auth/me")
        assert first.status_code == second.status_code == 503
        for response in (first, second):
            envelope = ErrorEnvelope.model_validate_json(response.text)
            assert UUID(envelope.meta.request_id).version == 4
            assert envelope.meta.request_id == response.headers["X-Request-ID"]
            assert envelope.meta.contract_version == "1.0.0"
            assert all(value is None for value in envelope.meta.versions.model_dump().values())
            assert response.headers["Cache-Control"] == "no-store"
        assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
        missing = client.get("/v1/glossary")
        assert missing.status_code == 404
        assert ErrorEnvelope.model_validate_json(missing.text).error.code == "NOT_FOUND"
        comparison_method = client.get("/v1/compare")
        assert comparison_method.status_code == 405
        assert comparison_method.headers["allow"] == "POST"
        assert (
            ErrorEnvelope.model_validate_json(comparison_method.text).error.code
            == "METHOD_NOT_ALLOWED"
        )
        wrong_method = client.post("/v1/auth/me")
        assert wrong_method.status_code == 405
        assert wrong_method.headers["allow"] == "GET"
        assert (
            ErrorEnvelope.model_validate_json(wrong_method.text).error.code == "METHOD_NOT_ALLOWED"
        )


def test_validation_and_unhandled_errors_never_echo_values_or_dynamic_field_names() -> None:
    application = create_app(Settings(environment="test"))

    @application.post("/v1/test-contract-only")
    def validated(body: StrictBody) -> dict[str, int]:
        return {"count": body.count}

    @application.get("/v1/test-error-only")
    def failed() -> None:
        raise RuntimeError("synthetic-secret-database-diagnostic")

    @application.get("/v1/test-http-error-only")
    def failed_http() -> None:
        raise HTTPException(status_code=400, detail="synthetic-secret-database-diagnostic")

    origin = "http://127.0.0.1:5173"
    with TestClient(application) as client:
        validation = client.post(
            "/v1/test-contract-only",
            json={"count": "synthetic-private-value", "synthetic-private-key": 1},
        )
        assert validation.status_code == 422
        envelope = ErrorEnvelope.model_validate_json(validation.text)
        assert envelope.error.code == "VALIDATION_ERROR"
        assert [detail.location for detail in envelope.error.details] == ["body"]
        assert "synthetic-private" not in validation.text
        for path, expected in (("/v1/test-error-only", 500), ("/v1/test-http-error-only", 400)):
            response = client.get(path, headers={"Origin": origin})
            assert response.status_code == expected
            assert "synthetic-secret" not in response.text
            ErrorEnvelope.model_validate_json(response.text)
            assert response.headers["access-control-allow-origin"] == origin
            assert set(response.headers["access-control-expose-headers"].split(", ")) == {
                "X-Request-ID",
                "ETag",
                "Content-Range",
                "Accept-Ranges",
                "Content-Length",
                "X-Corpus-Version-ID",
            }


def test_protocol_exceptions_and_openapi_shapes_remain_explicit() -> None:
    service = AuthService(EmptyRepository(), AuthSettings(jwt_secret=SecretStr("ab" * 32)))
    with TestClient(create_app(Settings(environment="test"), auth_service=service)) as client:
        health = client.get("/health/live")
        assert set(health.json()) == {"status", "service", "environment"}
        token = client.post("/v1/auth/token", data={"grant_type": "invalid"})
        assert token.status_code == 422
        assert token.json() == {"detail": "Invalid authentication request."}
        assert token.headers["cache-control"] == "no-store"
        schema = client.get("/openapi.json").json()
        source_operations = schema["paths"]["/v1/filing-versions/{filing_version_id}/source.pdf"]
        assert source_operations["get"]["operationId"] != source_operations["head"]["operationId"]
        for path in ("/v1/auth/me", "/v1/auth/admin/me"):
            responses = schema["paths"][path]["get"]["responses"]
            assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
                "/UserEnvelope"
            )
            for status in ("401", "403", "422", "500", "503"):
                assert responses[status]["content"]["application/json"]["schema"]["$ref"].endswith(
                    "/ErrorEnvelope"
                )
        token_schema = schema["paths"]["/v1/auth/token"]["post"]["responses"]["200"]
        assert token_schema["content"]["application/json"]["schema"]["$ref"].endswith(
            "/TokenResponse"
        )
        ResponseMeta.model_json_schema()


def test_cors_preflights_keep_auth_cache_headers_and_fresh_server_request_ids() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        responses = [
            client.options(
                "/v1/auth/token",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type, Authorization",
                    "X-Request-ID": "untrusted-caller-id",
                },
            )
            for origin in ("http://127.0.0.1:5173", "https://unapproved.example")
        ]
    allowed, denied = responses
    assert allowed.status_code == 200 and allowed.text == "OK"
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers
    for response in responses:
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
        assert UUID(response.headers["X-Request-ID"]).version == 4
    assert allowed.headers["X-Request-ID"] != denied.headers["X-Request-ID"]
