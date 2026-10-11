"""Shared database-authoritative bearer and admin dependencies."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from regintel.auth.errors import AuthUnavailable, InvalidAuthentication
from regintel.auth.service import AuthService
from regintel.auth.types import User

_bearer = OAuth2PasswordBearer(tokenUrl="/v1/auth/token", auto_error=False)


def user_dependency(service: AuthService | None, *, admin: bool = False) -> Callable[..., User]:
    def authenticated(token: Annotated[str | None, Depends(_bearer)]) -> User:
        if service is None:
            raise HTTPException(503, "Authentication is unavailable.")
        if token is None:
            raise HTTPException(
                401, "Invalid bearer token.", headers={"WWW-Authenticate": "Bearer"}
            )
        try:
            user = service.current_user(token)
        except InvalidAuthentication:
            raise HTTPException(
                401, "Invalid bearer token.", headers={"WWW-Authenticate": "Bearer"}
            ) from None
        except AuthUnavailable:
            raise HTTPException(503, "Authentication is unavailable.") from None
        if admin and user.role != "admin":
            raise HTTPException(403, "Administrator role required.")
        return user

    return authenticated
