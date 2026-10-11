"""M0.4 OAuth2 login and safe identity endpoints; business routes arrive later."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestFormStrict
from pydantic import BaseModel, Field

from regintel.auth.dependencies import user_dependency
from regintel.auth.errors import AuthUnavailable, InvalidAuthentication
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ErrorEnvelope, UserEnvelope, UserIdentity

PublicUser = UserIdentity


class TokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status_code=401, detail=message, headers={"WWW-Authenticate": "Bearer"})


def create_auth_router(service: AuthService | None) -> APIRouter:
    router = APIRouter(prefix="/v1/auth", tags=["authentication"])

    def configured_service() -> AuthService:
        if service is None:
            raise HTTPException(status_code=503, detail="Authentication is unavailable.")
        return service

    current_user = user_dependency(service)

    @router.post("/token", response_model=TokenResponse)
    def login(
        form: Annotated[OAuth2PasswordRequestFormStrict, Depends()],
        configured: Annotated[AuthService, Depends(configured_service)],
    ) -> TokenResponse:
        try:
            token = configured.login(form.username, form.password)
        except InvalidAuthentication:
            raise _unauthorized("Invalid credentials.") from None
        except AuthUnavailable:
            raise HTTPException(status_code=503, detail="Authentication is unavailable.") from None
        return TokenResponse(access_token=token, expires_in=configured.settings.token_ttl_seconds)

    identity_errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (401, 403, 422, 500, 503)
    }

    @router.get("/me", response_model=UserEnvelope, responses=identity_errors)
    def me(request: Request, user: Annotated[User, Depends(current_user)]) -> UserEnvelope:
        return UserEnvelope(
            data=PublicUser(id=str(user.id), username=user.username, role=user.role),
            meta=response_meta(request),
        )

    @router.get("/admin/me", response_model=UserEnvelope, responses=identity_errors)
    def admin_me(request: Request, user: Annotated[User, Depends(current_user)]) -> UserEnvelope:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Administrator role required.")
        return UserEnvelope(
            data=PublicUser(id=str(user.id), username=user.username, role=user.role),
            meta=response_meta(request),
        )

    return router
