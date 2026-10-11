"""Explicit selected-file authentication settings, separate from process liveness."""

import re
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from regintel.auth.types import SeedAccount, normalize_username


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    jwt_secret: SecretStr
    issuer: str = Field(default="regintel-finance", min_length=3, max_length=128)
    audience: str = Field(default="regintel-api", min_length=3, max_length=128)
    token_ttl_seconds: int = Field(default=1800, ge=60, le=3600)

    @field_validator("jwt_secret")
    @classmethod
    def require_generated_key(cls, value: SecretStr) -> SecretStr:
        if re.fullmatch(r"[0-9a-f]{64}", value.get_secret_value()) is None:
            raise ValueError("Use a newly generated64-character hexadecimal JWT secret.")
        return value


def _read_values(env_file: Path) -> dict[str, str | None]:
    if not env_file.is_file():
        raise ValueError("The explicitly selected authentication environment file is missing.")
    return dict(dotenv_values(env_file, encoding="utf-8", interpolate=False))


def load_auth_settings(env_file: Path) -> AuthSettings:
    try:
        values = _read_values(env_file)
        secret = values.get("REGINTEL_JWT_SECRET")
        if secret is None:
            raise ValueError("Authentication configuration is incomplete.")
        return AuthSettings(
            jwt_secret=SecretStr(secret),
            issuer=values.get("REGINTEL_AUTH_ISSUER") or "regintel-finance",
            audience=values.get("REGINTEL_AUTH_AUDIENCE") or "regintel-api",
            token_ttl_seconds=int(values.get("REGINTEL_AUTH_TOKEN_TTL_SECONDS") or "1800"),
        )
    except (OSError, UnicodeError, ValidationError, ValueError):
        raise ValueError(
            "Authentication configuration is missing or invalid; secrets omitted."
        ) from None


def load_seed_accounts(env_file: Path) -> tuple[SeedAccount, ...]:
    try:
        values = _read_values(env_file)
        admin_name = values.get("REGINTEL_SEED_ADMIN_USERNAME")
        learner_name = values.get("REGINTEL_SEED_LEARNER_USERNAME")
        admin_password = values.get("REGINTEL_SEED_ADMIN_PASSWORD")
        learner_password = values.get("REGINTEL_SEED_LEARNER_PASSWORD")
        if not all((admin_name, learner_name, admin_password, learner_password)):
            raise ValueError("Seed configuration is incomplete.")
        assert admin_name is not None and learner_name is not None
        assert admin_password is not None and learner_password is not None
        return (
            SeedAccount(normalize_username(admin_name), SecretStr(admin_password), "admin"),
            SeedAccount(normalize_username(learner_name), SecretStr(learner_password), "learner"),
        )
    except (OSError, UnicodeError, ValueError):
        raise ValueError("Seed configuration is missing or invalid; secrets omitted.") from None
