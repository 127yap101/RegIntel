"""HTTP and environment-boundary checks for the implemented foundation."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from regintel.config import Settings
from regintel.main import create_app


def test_liveness_is_typed_and_environment_specific() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "RegIntel Finance",
        "environment": "test",
    }


def test_only_configured_origins_pass_browser_preflight() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        allowed = client.options(
            "/health/live",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = client.options(
            "/health/live",
            headers={
                "Origin": "https://unapproved.example",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_unknown_environment_fails_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGINTEL_ENVIRONMENT", "invalid")
    with pytest.raises(ValidationError, match="environment"):
        Settings()


def test_unimplemented_business_route_has_no_fabricated_data() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/v1/compare")
    assert response.status_code == 404


def test_unconfigured_published_reads_do_not_fabricate_company_data() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/v1/companies")
    assert response.status_code == 503
    assert "data" not in response.json()
