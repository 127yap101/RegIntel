"""M3/M4 wire export root; existing M1 and M2 endpoint contracts retain ownership."""

from regintel.contracts.models import ContractModel
from regintel.learning.draft_pack import LearningStarterPack
from regintel.learning.models import (
    DefinitionDraft,
    DefinitionQueue,
    GlossaryVersion,
    LearningOverview,
    LearningReview,
    PublishLearning,
    ReviewedDefinition,
    StoredDefinition,
)
from regintel.learning.service import LearningContextRequest, LearningExplanation
from regintel.portfolio.analytics import PortfolioAnalytics
from regintel.portfolio.models import LedgerPage, OrderReceipt, OrderRequest, PortfolioAccount


class ModuleWire(ContractModel):
    definition_input: DefinitionDraft
    definition: StoredDefinition
    drafts: DefinitionQueue
    starter_pack: LearningStarterPack
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
    analytics: PortfolioAnalytics
