"""Pinned Argon2id policy with bounded, exact password bytes and random salts."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher

MAX_PASSWORD_BYTES = 1024
MIN_SEED_PASSWORD_BYTES = 16
_hasher = PasswordHash(
    (Argon2Hasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16),)
)


def password_within_bounds(password: str) -> bool:
    try:
        return 0 < len(password.encode("utf-8")) <= MAX_PASSWORD_BYTES
    except UnicodeError:
        return False


def hash_password(password: str) -> str:
    if (
        not password_within_bounds(password)
        or len(password.encode("utf-8")) < MIN_SEED_PASSWORD_BYTES
    ):
        raise ValueError("Seed passwords must contain 16–1024 UTF-8 bytes.")
    return _hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    if not password_within_bounds(password) or not encoded.startswith("$argon2id$"):
        return False
    try:
        return _hasher.verify(password, encoded)
    except (UnknownHashError, ValueError):
        return False
