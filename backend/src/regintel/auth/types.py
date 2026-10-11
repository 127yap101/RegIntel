"""Small immutable account types shared by storage and authentication services."""

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import SecretStr

Role = Literal["admin", "learner"]
USERNAME_PATTERN = re.compile(r"[a-z][a-z0-9._-]{2,63}\Z", re.ASCII)


@dataclass(frozen=True)
class User:
    id: UUID
    username: str
    password_hash: SecretStr
    role: Role
    is_active: bool
    auth_version: int


@dataclass(frozen=True)
class SeedAccount:
    username: str
    password: SecretStr
    role: Role


@dataclass(frozen=True)
class SeedReport:
    created: tuple[str, ...]
    existing: tuple[str, ...]


def normalize_username(value: str) -> str:
    """Canonicalize bounded ASCII account names without echoing invalid input."""
    normalized = value.strip()
    if not normalized.isascii():
        raise ValueError("A valid ASCII username of 3 to 64 characters is required.")
    normalized = normalized.lower()
    if USERNAME_PATTERN.fullmatch(normalized) is None:
        raise ValueError("A valid ASCII username of 3 to 64 characters is required.")
    return normalized
