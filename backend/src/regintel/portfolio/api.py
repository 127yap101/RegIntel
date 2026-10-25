"""Authenticated per-user virtual accounts/orders; no client prices or real execution."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import ContractModel, ErrorEnvelope, SuccessEnvelope
from regintel.portfolio.analytics import PortfolioAnalytics
from regintel.portfolio.models import LedgerPage, OrderReceipt, OrderRequest, PortfolioAccount
from regintel.portfolio.repository import (
    PortfolioConflict,
    PortfolioForbidden,
    PortfolioNotFound,
    PortfolioUnavailable,
)
from regintel.portfolio.service import PortfolioService
from regintel.reads.repository import ReadNotFound, ReadUnavailable


class CreateVirtualAccount(ContractModel):
    """The server fixes the opening virtual credit; no client financial state is accepted."""


def perform[T](work: Callable[[], T]) -> T:
    try:
        return work()
    except PortfolioForbidden:
        raise HTTPException(403, "A current account owner is required.") from None
    except (PortfolioNotFound, ReadNotFound):
        raise HTTPException(
            404, "The selected virtual account or published company is unavailable."
        ) from None
    except PortfolioConflict:
        raise HTTPException(409, "The virtual request or source context conflicts.") from None
    except (PortfolioUnavailable, ReadUnavailable):
        raise HTTPException(503, "Virtual portfolio prerequisites are unavailable.") from None


def create_portfolio_router(
    auth: AuthService | None, service: PortfolioService | None
) -> APIRouter:
    router = APIRouter(tags=["M4 virtual portfolio"])
    reader = user_dependency(auth)
    errors: dict[int | str, dict[str, object]] = {
        status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409, 422, 503)
    }

    def ready() -> PortfolioService:
        if service is None:
            raise HTTPException(503, "Virtual portfolio storage is unavailable.")
        return service

    def envelope[T](
        data: T, request: Request, version: str, corpus: str | None = None, quote: str | None = None
    ) -> SuccessEnvelope[T]:
        meta = response_meta(request)
        meta = meta.model_copy(
            update={
                "versions": meta.versions.model_copy(
                    update={
                        "portfolio_version_id": version,
                        "corpus_version_id": corpus,
                        "quote_version_id": quote,
                    }
                )
            }
        )
        return SuccessEnvelope(data=data, meta=meta)

    @router.post(
        "/v1/portfolio/accounts", response_model=SuccessEnvelope[PortfolioAccount], responses=errors
    )
    def create(
        body: CreateVirtualAccount, request: Request, user: Annotated[User, Depends(reader)]
    ) -> SuccessEnvelope[PortfolioAccount]:
        data = perform(lambda: ready().repository.create(user))
        return envelope(data, request, data.portfolio_version_id)

    @router.get("/v1/portfolio", response_model=SuccessEnvelope[PortfolioAccount], responses=errors)
    def account(
        request: Request, user: Annotated[User, Depends(reader)]
    ) -> SuccessEnvelope[PortfolioAccount]:
        data = perform(lambda: ready().repository.account(user))
        return envelope(data, request, data.portfolio_version_id)

    @router.post(
        "/v1/portfolio/orders", response_model=SuccessEnvelope[OrderReceipt], responses=errors
    )
    def order(
        body: OrderRequest, request: Request, user: Annotated[User, Depends(reader)]
    ) -> SuccessEnvelope[OrderReceipt]:
        data = perform(lambda: ready().submit(body, user))
        return envelope(
            data,
            request,
            data.portfolio_version_id,
            body.corpus_version_id,
            data.entry.quote.quote_version_id if data.entry.quote else None,
        )

    @router.get(
        "/v1/portfolio/ledger", response_model=SuccessEnvelope[LedgerPage], responses=errors
    )
    def ledger(
        request: Request,
        user: Annotated[User, Depends(reader)],
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> SuccessEnvelope[LedgerPage]:
        data = perform(lambda: ready().repository.ledger(user, offset=offset, limit=limit))
        return envelope(data, request, data.portfolio_version_id)

    @router.get(
        "/v1/portfolio/analytics",
        response_model=SuccessEnvelope[PortfolioAnalytics],
        responses=errors,
    )
    def analytics(
        request: Request, user: Annotated[User, Depends(reader)]
    ) -> SuccessEnvelope[PortfolioAnalytics]:
        data = perform(lambda: ready().repository.analytics(user))
        return envelope(data, request, data.portfolio_version_id)

    return router
