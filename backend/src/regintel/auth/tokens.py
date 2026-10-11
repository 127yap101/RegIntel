"""Fixed-algorithm JWTs with strict application claims and bounded lifetimes."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from regintel.auth.config import AuthSettings
from regintel.auth.errors import InvalidAuthentication
from regintel.auth.types import User

MAX_TOKEN_CHARACTERS = 8192
REQUIRED_CLAIMS = ("iss", "aud", "sub", "iat", "exp", "jti", "auth_version")


class TokenClaims(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    iss: str
    aud: str
    sub: str
    iat: int = Field(ge=0)
    exp: int = Field(ge=1)
    jti: str
    auth_version: int = Field(ge=1)

    @field_validator("sub", "jti")
    @classmethod
    def canonical_uuid4(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("Canonical UUIDv4 required.")
        return value


def issue_token(user: User, settings: AuthSettings) -> str:
    now = int(datetime.now(UTC).timestamp())
    claims = TokenClaims(
        iss=settings.issuer,
        aud=settings.audience,
        sub=str(user.id),
        iat=now,
        exp=now + settings.token_ttl_seconds,
        jti=str(uuid4()),
        auth_version=user.auth_version,
    )
    return jwt.encode(
        claims.model_dump(), settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )


def validate_token(token: str, settings: AuthSettings) -> TokenClaims:
    if not token or len(token) > MAX_TOKEN_CHARACTERS:
        raise InvalidAuthentication("Invalid bearer token.")
    try:
        header = jwt.get_unverified_header(token)
        if header.get("typ") != "JWT" or header.get("crit") is not None:
            raise InvalidAuthentication("Invalid bearer token.")
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.issuer,
            audience=settings.audience,
            options={
                "require": list(REQUIRED_CLAIMS),
                "strict_aud": True,
                "enforce_minimum_key_length": True,
            },
        )
        claims = TokenClaims.model_validate(payload)
        if claims.exp - claims.iat != settings.token_ttl_seconds:
            raise InvalidAuthentication("Invalid bearer token.")
        return claims
    except (jwt.InvalidTokenError, ValidationError, ValueError, TypeError):
        raise InvalidAuthentication("Invalid bearer token.") from None
