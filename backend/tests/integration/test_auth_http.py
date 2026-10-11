"""Real PostgreSQL, Argon2id and JWT checks through the M0.4 HTTP boundary."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr

from regintel.auth.config import AuthSettings
from regintel.auth.errors import AuthUnavailable
from regintel.auth.passwords import hash_password
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.service import AuthService
from regintel.auth.types import SeedAccount, User
from regintel.config import Settings
from regintel.contracts.models import ErrorEnvelope
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import connect_database
from regintel.main import create_app

pytestmark = pytest.mark.integration

ADMIN_PASSWORD = "Synthetic admin password 2026!"
LEARNER_PASSWORD = "Synthetic learner password 2026!"


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(jwt_secret=SecretStr("ab" * 32))


@pytest.fixture
def auth_client(
    auth_database: DatabaseSettings, auth_settings: AuthSettings
) -> Iterator[TestClient]:
    report = seed_users(
        auth_database,
        (
            SeedAccount("admin", SecretStr(ADMIN_PASSWORD), "admin"),
            SeedAccount("learner", SecretStr(LEARNER_PASSWORD), "learner"),
        ),
    )
    assert report.created == ("admin", "learner")
    service = AuthService(PostgreSQLAuthRepository(auth_database), auth_settings)
    with TestClient(create_app(Settings(environment="test"), auth_service=service)) as client:
        yield client


def assert_no_cache(response: Response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def login(client: TestClient, username: str, password: str) -> Response:
    response = client.post(
        "/v1/auth/token",
        data={"grant_type": "password", "username": username, "password": password},
    )
    assert_no_cache(response)
    return response


def login_token(client: TestClient, username: str, password: str) -> str:
    response = login(client, username, password)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"access_token", "token_type", "expires_in"}
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == 1800
    token = payload["access_token"]
    assert isinstance(token, str)
    return token


def identity(client: TestClient, token: str, path: str = "/v1/auth/me") -> Response:
    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert_no_cache(response)
    return response


def assert_invalid_token(response: Response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"] == {
        "code": "UNAUTHENTICATED",
        "message": "Invalid bearer token.",
        "details": [],
    }
    envelope = ErrorEnvelope.model_validate_json(response.text)
    assert envelope.meta.request_id == response.headers["x-request-id"]
    assert_no_cache(response)


@pytest.mark.parametrize(
    ("username", "password", "role"),
    [("admin", ADMIN_PASSWORD, "admin"), ("learner", LEARNER_PASSWORD, "learner")],
)
def test_login_and_public_identity_expose_only_safe_fields(
    auth_client: TestClient, username: str, password: str, role: str
) -> None:
    token = login_token(auth_client, username, password)
    response = identity(auth_client, token)
    assert response.status_code == 200
    envelope = response.json()
    assert set(envelope) == {"data", "meta"}
    assert envelope["meta"]["request_id"] == response.headers["x-request-id"]
    assert envelope["meta"]["contract_version"] == "1.0.0"
    assert all(value is None for value in envelope["meta"]["versions"].values())
    payload = envelope["data"]
    assert set(payload) == {"id", "username", "role"}
    assert UUID(payload["id"]).version == 4
    assert payload["username"] == username
    assert payload["role"] == role
    assert password not in response.text
    assert token not in response.text
    assert "$argon2" not in response.text


def test_administrator_route_enforces_current_database_role(auth_client: TestClient) -> None:
    admin = login_token(auth_client, "admin", ADMIN_PASSWORD)
    learner = login_token(auth_client, "learner", LEARNER_PASSWORD)
    assert identity(auth_client, admin, "/v1/auth/admin/me").status_code == 200
    denied = identity(auth_client, learner, "/v1/auth/admin/me")
    assert denied.status_code == 403
    assert denied.json()["error"] == {
        "code": "FORBIDDEN",
        "message": "Administrator role required.",
        "details": [],
    }


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("admin", "Incorrect synthetic password!"),
        ("unknown", ADMIN_PASSWORD),
        ("' OR 1=1--", ADMIN_PASSWORD),
    ],
)
def test_invalid_credentials_have_generic_challenge_without_echo(
    auth_client: TestClient, username: str, password: str
) -> None:
    response = login(auth_client, username, password)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid credentials."}
    assert username not in response.text
    assert password not in response.text


@pytest.mark.parametrize("token", ["not.a.jwt", "x" * 8193])
def test_invalid_or_oversized_tokens_are_rejected(auth_client: TestClient, token: str) -> None:
    assert_invalid_token(identity(auth_client, token))


@pytest.mark.parametrize("authorization", [None, "Basic c3ludGhldGljOnBhc3N3b3Jk"])
def test_missing_or_non_bearer_authentication_is_rejected(
    auth_client: TestClient, authorization: str | None
) -> None:
    headers = {"Authorization": authorization} if authorization is not None else {}
    assert_invalid_token(auth_client.get("/v1/auth/me", headers=headers))


def test_explicit_version_revocation_invalidates_existing_token(
    auth_client: TestClient, auth_database: DatabaseSettings
) -> None:
    token = login_token(auth_client, "learner", LEARNER_PASSWORD)
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET auth_version = auth_version + 1 WHERE username = %s",
            ("learner",),
        )
    assert_invalid_token(identity(auth_client, token))
    replacement = login_token(auth_client, "learner", LEARNER_PASSWORD)
    assert identity(auth_client, replacement).status_code == 200


def test_role_changes_revoke_tokens_and_new_tokens_follow_database_role(
    auth_client: TestClient, auth_database: DatabaseSettings
) -> None:
    learner = login_token(auth_client, "learner", LEARNER_PASSWORD)
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET role = %s WHERE username = %s", ("admin", "learner")
        )
    assert_invalid_token(identity(auth_client, learner))
    promoted = login_token(auth_client, "learner", LEARNER_PASSWORD)
    assert identity(auth_client, promoted, "/v1/auth/admin/me").status_code == 200
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET role = %s WHERE username = %s", ("learner", "learner")
        )
    assert_invalid_token(identity(auth_client, promoted))
    demoted = login_token(auth_client, "learner", LEARNER_PASSWORD)
    assert identity(auth_client, demoted).json()["data"]["role"] == "learner"
    assert identity(auth_client, demoted, "/v1/auth/admin/me").status_code == 403


def test_deactivation_blocks_login_and_token_reuse_even_after_reactivation(
    auth_client: TestClient, auth_database: DatabaseSettings
) -> None:
    original = login_token(auth_client, "learner", LEARNER_PASSWORD)
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET is_active = false WHERE username = %s", ("learner",)
        )
    assert_invalid_token(identity(auth_client, original))
    inactive_login = login(auth_client, "learner", LEARNER_PASSWORD)
    assert inactive_login.status_code == 401
    assert inactive_login.headers["www-authenticate"] == "Bearer"
    assert inactive_login.json() == {"detail": "Invalid credentials."}
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET is_active = true WHERE username = %s", ("learner",)
        )
    assert_invalid_token(identity(auth_client, original))
    replacement = login_token(auth_client, "learner", LEARNER_PASSWORD)
    assert identity(auth_client, replacement).status_code == 200


def test_password_change_revokes_token_and_preserves_exact_new_password(
    auth_client: TestClient, auth_database: DatabaseSettings
) -> None:
    original = login_token(auth_client, "learner", LEARNER_PASSWORD)
    replacement_password = "  Synthetic changed password 2026!  "
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET password_hash = %s WHERE username = %s",
            (hash_password(replacement_password), "learner"),
        )
    assert_invalid_token(identity(auth_client, original))
    assert login(auth_client, "learner", LEARNER_PASSWORD).status_code == 401
    assert login(auth_client, "learner", replacement_password.strip()).status_code == 401
    replacement = login_token(auth_client, "learner", replacement_password)
    assert identity(auth_client, replacement).status_code == 200


def test_deleted_account_cannot_reuse_token_or_login(
    auth_client: TestClient, auth_database: DatabaseSettings
) -> None:
    token = login_token(auth_client, "learner", LEARNER_PASSWORD)
    with connect_database(auth_database) as connection:
        connection.execute("DELETE FROM regintel.users WHERE username = %s", ("learner",))
    assert_invalid_token(identity(auth_client, token))
    deleted_login = login(auth_client, "learner", LEARNER_PASSWORD)
    assert deleted_login.status_code == 401
    assert deleted_login.headers["www-authenticate"] == "Bearer"
    assert deleted_login.json() == {"detail": "Invalid credentials."}


def test_invalid_form_validation_omits_sensitive_input(auth_client: TestClient) -> None:
    sensitive = "Synthetic sensitive validation input!"
    response = auth_client.post(
        "/v1/auth/token",
        data={"grant_type": sensitive, "username": sensitive, "password": sensitive},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid authentication request."}
    assert sensitive not in response.text
    assert_no_cache(response)


def test_login_browser_preflight_requires_configured_origin(auth_client: TestClient) -> None:
    headers = {
        "Origin": "http://127.0.0.1:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, Authorization",
    }
    allowed = auth_client.options("/v1/auth/token", headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == headers["Origin"]
    assert_no_cache(allowed)
    headers["Origin"] = "https://unapproved.example"
    denied = auth_client.options("/v1/auth/token", headers=headers)
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    assert_no_cache(denied)


class UnavailableRepository:
    """Exercise sanitized failure handling without stopping shared infrastructure."""

    def get_by_username(self, username: str) -> User | None:
        raise AuthUnavailable("Synthetic private database connection diagnostic.")

    def get_by_id(self, user_id: UUID) -> User | None:
        raise AuthUnavailable("Synthetic private database connection diagnostic.")


def test_storage_outage_is_sanitized_for_login_and_protected_identity(
    auth_client: TestClient, auth_settings: AuthSettings
) -> None:
    valid_token = login_token(auth_client, "learner", LEARNER_PASSWORD)
    service = AuthService(UnavailableRepository(), auth_settings)
    with TestClient(create_app(Settings(environment="test"), auth_service=service)) as client:
        responses = [
            login(client, "learner", LEARNER_PASSWORD),
            identity(client, valid_token),
        ]
    for response, enveloped in zip(responses, (False, True), strict=True):
        assert response.status_code == 503
        if enveloped:
            assert set(response.json()) == {"error", "meta"}
            assert response.json()["error"] == {
                "code": "SERVICE_UNAVAILABLE",
                "message": "Authentication is unavailable.",
                "details": [],
            }
        else:
            assert response.json() == {"detail": "Authentication is unavailable."}
        assert "diagnostic" not in response.text
        assert LEARNER_PASSWORD not in response.text
        assert valid_token not in response.text
        assert_no_cache(response)
