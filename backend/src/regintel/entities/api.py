"""Admin-only evidence-backed entity registration, resolution and review."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ContractModel, ErrorEnvelope, SuccessEnvelope
from regintel.contracts.primitives import CanonicalId
from regintel.entities.models import EntityRegistration, EntityReview, EntityRun
from regintel.entities.repository import (
    EntityAuthorizationError,
    EntityConflict,
    EntityNotFound,
    EntityRegistryChanged,
    EntityRepository,
    EntitySourceError,
    EntityUnavailable,
)


class RegistrationReceipt(ContractModel):
    entity_id: CanonicalId
    already_exists: bool


class RegistrationEnvelope(SuccessEnvelope[RegistrationReceipt]):
    pass


class RunRequest(ContractModel):
    parse_version_id: CanonicalId


class RunData(ContractModel):
    run: EntityRun
    reviews: tuple[EntityReview, ...]


class RunEnvelope(SuccessEnvelope[RunData]):
    pass


class ReviewReceipt(ContractModel):
    review_id: CanonicalId
    already_exists: bool


class ReviewEnvelope(SuccessEnvelope[ReviewReceipt]):
    pass


class EntityService:
    def __init__(self, repository: EntityRepository) -> None:
        self.repository = repository

    def resolve(self, parse_id: str, user: User) -> EntityRun:
        from regintel.entities.resolution import EntityResolver, current_configuration

        snapshot = self.repository.snapshot()
        evidence, artifact_sha = self.repository.evidence_for_parse(parse_id)
        run = EntityResolver(snapshot, current_configuration()).run(evidence, artifact_sha)
        return self.repository.save_run(run, user)


def create_entity_router(auth: AuthService | None, service: EntityService | None) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/entities", tags=["entity resolution"])
    admin = user_dependency(auth, admin=True)

    def configured() -> EntityService:
        if service is None:
            raise HTTPException(503, "Entity resolution is unavailable.")
        return service

    def mapped(error: Exception) -> HTTPException:
        if isinstance(error, EntityAuthorizationError):
            return HTTPException(403, "Administrator approval is unavailable.")
        if isinstance(error, EntityUnavailable):
            return HTTPException(503, "Entity resolution is unavailable.")
        if isinstance(error, EntityNotFound):
            return HTTPException(404, "Entity source or run not found.")
        if isinstance(error, (EntityConflict, EntityRegistryChanged)):
            return HTTPException(409, "Entity registry or request conflicts with stored state.")
        if isinstance(error, (EntitySourceError, ValueError)):
            return HTTPException(422, "Entity source support is invalid or exceeds a bound.")
        return HTTPException(503, "Entity resolution is unavailable.")

    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 422, 500, 503)
    }
    failures = (
        EntityAuthorizationError,
        EntityNotFound,
        EntityConflict,
        EntityRegistryChanged,
        EntitySourceError,
        EntityUnavailable,
        psycopg.Error,
        OSError,
        ImportError,
        ValueError,
    )

    @router.post("", response_model=RegistrationEnvelope, responses=errors)
    def register(
        request: Request,
        body: EntityRegistration,
        user: Annotated[User, Depends(admin)],
        entities: Annotated[EntityService, Depends(configured)],
    ) -> RegistrationEnvelope:
        try:
            created = entities.repository.register(body, user)
        except failures as error:
            raise mapped(error) from None
        return RegistrationEnvelope(
            data=RegistrationReceipt(entity_id=body.id, already_exists=not created),
            meta=response_meta(request),
        )

    @router.post("/runs", response_model=RunEnvelope, responses=errors)
    def resolve(
        request: Request,
        body: RunRequest,
        user: Annotated[User, Depends(admin)],
        entities: Annotated[EntityService, Depends(configured)],
    ) -> RunEnvelope:
        try:
            run = entities.resolve(body.parse_version_id, user)
            reviews = entities.repository.reviews(run.id)
        except failures as error:
            raise mapped(error) from None
        meta = response_meta(request)
        return RunEnvelope(
            data=RunData(run=run, reviews=reviews),
            meta=meta.model_copy(
                update={
                    "versions": meta.versions.model_copy(
                        update={"parse_version_id": run.parse_version_id}
                    )
                }
            ),
        )

    @router.get("/runs/{run_id}", response_model=RunEnvelope, responses=errors)
    def get_run(
        request: Request,
        run_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        entities: Annotated[EntityService, Depends(configured)],
    ) -> RunEnvelope:
        try:
            run = entities.repository.get_run(run_id)
            if run is None:
                raise EntityNotFound()
            reviews = entities.repository.reviews(run_id)
        except failures as error:
            raise mapped(error) from None
        meta = response_meta(request)
        return RunEnvelope(
            data=RunData(run=run, reviews=reviews),
            meta=meta.model_copy(
                update={
                    "versions": meta.versions.model_copy(
                        update={"parse_version_id": run.parse_version_id}
                    )
                }
            ),
        )

    @router.post("/reviews", response_model=ReviewEnvelope, responses=errors)
    def review(
        request: Request,
        body: EntityReview,
        user: Annotated[User, Depends(admin)],
        entities: Annotated[EntityService, Depends(configured)],
    ) -> ReviewEnvelope:
        try:
            created = entities.repository.review(body, user)
        except failures as error:
            raise mapped(error) from None
        return ReviewEnvelope(
            data=ReviewReceipt(review_id=body.id, already_exists=not created),
            meta=response_meta(request),
        )

    return router
