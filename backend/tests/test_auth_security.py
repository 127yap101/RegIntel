"""Actual Argon2/JWT boundary tests using synthetic credentials, no database."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid1, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from regintel.auth.config import AuthSettings, load_auth_settings, load_seed_accounts
from regintel.auth.errors import AuthUnavailable, InvalidAuthentication
from regintel.auth.passwords import hash_password, password_within_bounds, verify_password
from regintel.auth.service import AuthService
from regintel.auth.tokens import REQUIRED_CLAIMS, issue_token, validate_token
from regintel.auth.types import User
from regintel.config import Settings
from regintel.main import create_app

PASSWORD = "Synthetic auth password 2026!"


@pytest.fixture(scope="module")
def auth_settings() -> AuthSettings:
    return AuthSettings(jwt_secret=SecretStr("ab" * 32))


@pytest.fixture(scope="module")
def user() -> User:
    return User(uuid4(), "learner", SecretStr(hash_password(PASSWORD)), "learner", True, 1)


class MemoryRepository:
    def __init__(self, user: User) -> None:
        self.user: User | None = user
        self.unavailable = False

    def get_by_username(self, username: str) -> User | None:
        if self.unavailable:
            raise AuthUnavailable("Database unavailable.")
        return self.user if self.user and self.user.username == username else None

    def get_by_id(self, user_id: UUID) -> User | None:
        if self.unavailable:
            raise AuthUnavailable("Database unavailable.")
        return self.user if self.user and self.user.id == user_id else None


def test_argon2_random_salts_policy_and_exact_password() -> None:
    password = "  exact synthetic password é  "
    first = hash_password(password)
    second = hash_password(password)
    assert first != second
    assert first.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert verify_password(password, first)
    assert not verify_password(password.strip(), first)
    assert not verify_password("wrong", first)
    assert not verify_password(password, "$argon2id$malformed")
    assert not verify_password(password, "plaintext")


@pytest.mark.parametrize("value", ["", "x" * 1025, "🧪" * 257, "\ud800"])
def test_password_bounds_before_expensive_hashing(value: str) -> None:
    assert not password_within_bounds(value)
    assert not verify_password(value, "$argon2id$malformed")
    with pytest.raises(ValueError):
        hash_password(value)


def test_valid_token_has_fixed_claims_no_role_and_exact_lifetime(
    user: User, auth_settings: AuthSettings
) -> None:
    token = issue_token(user, auth_settings)
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    claims = validate_token(token, auth_settings)
    assert claims.sub == str(user.id)
    assert UUID(claims.jti).version == 4
    assert claims.exp - claims.iat == 1800
    assert set(claims.model_dump()) == set(REQUIRED_CLAIMS)


@pytest.mark.parametrize("missing", REQUIRED_CLAIMS)
def test_missing_claim_rejected(user: User, auth_settings: AuthSettings, missing: str) -> None:
    claims = validate_token(issue_token(user, auth_settings), auth_settings).model_dump()
    del claims[missing]
    token = jwt.encode(claims, auth_settings.jwt_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(InvalidAuthentication):
        validate_token(token, auth_settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("iss", "wrong-issuer"),
        ("aud", "wrong-audience"),
        ("aud", ["regintel-api"]),
        ("sub", str(uuid1())),
        ("sub", "not-a-uuid"),
        ("jti", str(uuid1())),
        ("jti", 5),
        ("iat", True),
        ("iat", "123"),
        ("exp", "4102444800"),
        ("exp", 4102444800.1),
        ("auth_version", True),
        ("auth_version", "1"),
        ("auth_version", 1.0),
        ("auth_version", 0),
        ("role", "admin"),
    ],
)
def test_strict_claim_types_and_values(
    user: User, auth_settings: AuthSettings, field: str, value: object
) -> None:
    claims = validate_token(issue_token(user, auth_settings), auth_settings).model_dump()
    claims[field] = value
    token = jwt.encode(claims, auth_settings.jwt_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(InvalidAuthentication):
        validate_token(token, auth_settings)


def test_expired_future_and_extended_lifetimes_rejected(
    user: User, auth_settings: AuthSettings
) -> None:
    now = int(datetime.now(UTC).timestamp())
    original = validate_token(issue_token(user, auth_settings), auth_settings).model_dump()
    for issued, expires in [(now - 3600, now - 1800), (now + 60, now + 1860), (now, now + 3600)]:
        claims = {**original, "iat": issued, "exp": expires}
        token = jwt.encode(claims, auth_settings.jwt_secret.get_secret_value(), algorithm="HS256")
        with pytest.raises(InvalidAuthentication):
            validate_token(token, auth_settings)


def test_signatures_algorithm_allowlist_and_header_policy(
    user: User, auth_settings: AuthSettings
) -> None:
    claims = validate_token(issue_token(user, auth_settings), auth_settings).model_dump()
    invalid = [
        jwt.encode(claims, "cd" * 32, algorithm="HS256"),
        jwt.encode(claims, auth_settings.jwt_secret.get_secret_value(), algorithm="HS384"),
        jwt.encode(claims, "", algorithm="none"),
        jwt.encode(claims, auth_settings.jwt_secret.get_secret_value(), headers={"typ": "other"}),
        jwt.encode(claims, auth_settings.jwt_secret.get_secret_value(), headers={"crit": ["x"]}),
        "malformed",
        "x" * 8193,
    ]
    for token in invalid:
        with pytest.raises(InvalidAuthentication):
            validate_token(token, auth_settings)


def test_account_authority_reload_revocation_and_deletion(
    user: User, auth_settings: AuthSettings
) -> None:
    repository = MemoryRepository(user)
    service = AuthService(repository, auth_settings)
    token = service.login(" LEARNER ", PASSWORD)
    assert service.current_user(token).id == user.id
    repository.user = replace(user, role="admin")
    assert service.current_user(token).role == "admin"
    for changed in [replace(user, is_active=False), replace(user, auth_version=2), None]:
        repository.user = changed
        with pytest.raises(InvalidAuthentication):
            service.current_user(token)
    repository.user = user
    repository.unavailable = True
    with pytest.raises(AuthUnavailable):
        service.current_user(token)


def test_unknown_username_verifies_dummy_without_acceptance(
    monkeypatch: pytest.MonkeyPatch, user: User, auth_settings: AuthSettings
) -> None:
    service = AuthService(MemoryRepository(user), auth_settings)
    calls: list[bool] = []

    def recording_verify(password: str, encoded: str) -> bool:
        calls.append(encoded.startswith("$argon2id$"))
        return verify_password(password, encoded)

    monkeypatch.setattr("regintel.auth.service.verify_password", recording_verify)
    with pytest.raises(InvalidAuthentication):
        service.login("unknown", PASSWORD)
    assert calls == [True]


def test_explicit_configuration_never_interpolates_ambient_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OTHER_SECRET", "must-not-be-imported")
    file = tmp_path / ".env.auth"
    file.write_text(
        f"REGINTEL_JWT_SECRET={'ab' * 32}\n"
        "REGINTEL_SEED_ADMIN_USERNAME=admin\n"
        "REGINTEL_SEED_ADMIN_PASSWORD=literal-${OTHER_SECRET}\n"
        "REGINTEL_SEED_LEARNER_USERNAME=learner\n"
        "REGINTEL_SEED_LEARNER_PASSWORD=another-synthetic-password\n",
        encoding="utf-8",
    )
    assert load_auth_settings(file).token_ttl_seconds == 1800
    assert load_seed_accounts(file)[0].password.get_secret_value() == "literal-${OTHER_SECRET}"
    file.write_text("REGINTEL_JWT_SECRET=${OTHER_SECRET}\n", encoding="utf-8")
    with pytest.raises(ValueError) as raised:
        load_auth_settings(file)
    assert "must-not-be-imported" not in str(raised.value)


def test_missing_or_placeholder_configuration_fails_safely(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_auth_settings(tmp_path / "missing")
    with pytest.raises(ValidationError) as raised:
        AuthSettings(jwt_secret=SecretStr("DO_NOT_ECHO_THIS_PLACEHOLDER"))
    assert "DO_NOT_ECHO_THIS_PLACEHOLDER" not in str(raised.value)


def test_auth_configuration_absent_leaves_health_public_and_auth_closed() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/v1/auth/me")
        assert response.status_code == 503
        assert response.json()["error"] == {
            "code": "SERVICE_UNAVAILABLE",
            "message": "Authentication is unavailable.",
            "details": [],
        }
        assert response.headers["cache-control"] == "no-store"
