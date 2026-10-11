"""Authentication always rechecks PostgreSQL account authority through a repository."""

import secrets
from typing import Protocol
from uuid import UUID

from regintel.auth.config import AuthSettings
from regintel.auth.errors import InvalidAuthentication
from regintel.auth.passwords import hash_password, password_within_bounds, verify_password
from regintel.auth.tokens import issue_token, validate_token
from regintel.auth.types import User, normalize_username


class UserRepository(Protocol):
    def get_by_username(self, username: str) -> User | None: ...

    def get_by_id(self, user_id: UUID) -> User | None: ...


class AuthService:
    def __init__(self, repository: UserRepository, settings: AuthSettings) -> None:
        self.repository = repository
        self.settings = settings
        self._dummy_hash = hash_password(secrets.token_urlsafe(32))

    def login(self, username: str, password: str) -> str:
        if not password_within_bounds(password):
            raise InvalidAuthentication("Invalid credentials.")
        try:
            normalized = normalize_username(username)
        except ValueError:
            verify_password(password, self._dummy_hash)
            raise InvalidAuthentication("Invalid credentials.") from None
        user = self.repository.get_by_username(normalized)
        encoded = user.password_hash.get_secret_value() if user else self._dummy_hash
        valid = verify_password(password, encoded)
        if not valid or user is None or not user.is_active:
            raise InvalidAuthentication("Invalid credentials.")
        return issue_token(user, self.settings)

    def current_user(self, token: str) -> User:
        claims = validate_token(token, self.settings)
        user = self.repository.get_by_id(UUID(claims.sub))
        if user is None or not user.is_active or user.auth_version != claims.auth_version:
            raise InvalidAuthentication("Invalid bearer token.")
        return user
