"""M3/M4 wire export root; existing M1 and M2 endpoint contracts retain ownership."""

from regintel.contracts.models import ContractModel
from regintel.learning.models import (
    DefinitionDraft,
    GlossaryVersion,
    LearningOverview,
    LearningReview,
    PublishLearning,
    ReviewedDefinition,
    StoredDefinition,
)
from regintel.learning.service import LearningContextRequest, LearningExplanation
from regintel.portfolio.models import LedgerPage, OrderReceipt, OrderRequest, PortfolioAccount


class ModuleWire(ContractModel):
    definition_input: DefinitionDraft
    definition: StoredDefinition
    review_input: LearningReview
    reviewed: ReviewedDefinition
    publication_input: PublishLearning
    glossary: GlossaryVersion
    learning_status: LearningOverview
    context_input: LearningContextRequest
    context: LearningExplanation
    portfolio: PortfolioAccount
    order_input: OrderRequest
    order: OrderReceipt
    ledger: LedgerPage
