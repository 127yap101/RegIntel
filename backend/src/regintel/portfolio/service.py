"""M4 accepts company identities only from the selected published M1 corpus."""

from regintel.auth.types import User
from regintel.portfolio.models import OrderReceipt, OrderRequest
from regintel.portfolio.repository import PortfolioConflict, PortfolioRepository
from regintel.reads.repository import ReadUnavailable
from regintel.reads.service import PublishedReadService


class PortfolioService:
    def __init__(self, repository: PortfolioRepository, reads: PublishedReadService | None) -> None:
        self.repository, self.reads = repository, reads

    def submit(self, request: OrderRequest, user: User) -> OrderReceipt:
        if self.reads is None:
            raise ReadUnavailable("A published company selection is required for virtual orders.")
        scope = self.reads.scope(request.corpus_version_id)
        if scope.view.state != "AVAILABLE":
            raise PortfolioConflict("The selected published company context is unavailable.")
        self.reads.facts(scope, request.company_id, 0, 1)
        return self.repository.submit(request, user)
