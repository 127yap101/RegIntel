"""Explicitly unreviewed starter drafts; loading never creates authoritative content."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import DateString, RawText
from regintel.learning.models import DefinitionDraft

DEFAULT_PACK = Path(__file__).resolve().parents[4] / "data/learning-starter-drafts.json"


class StarterDraft(ContractModel):
    key: Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    draft: DefinitionDraft

    @model_validator(mode="after")
    def requires_actual_review(self) -> Self:
        if self.draft.metric_ids or len(self.draft.sources) != 1:
            raise ValueError("Starter drafts require one source and no assumed M1 metric mapping.")
        return self


class LearningStarterPack(ContractModel):
    version: Literal["learning-starter-drafts-1"] = "learning-starter-drafts-1"
    status: Literal["DRAFT_UNREVIEWED"] = "DRAFT_UNREVIEWED"
    prepared_by: Literal["CODEX_DRAFT"] = "CODEX_DRAFT"
    prepared_on: DateString
    source_checked_on: DateString
    reviewed_by: None = None
    reviewed_on: None = None
    applicability: Annotated[RawText, Field(min_length=1, max_length=2000)]
    drafts: Annotated[tuple[StarterDraft, ...], Field(strict=False, min_length=1, max_length=20)]

    @model_validator(mode="after")
    def distinct_drafts(self) -> Self:
        if len({item.key for item in self.drafts}) != len(self.drafts) or len(
            {item.draft.term.casefold() for item in self.drafts}
        ) != len(self.drafts):
            raise ValueError("Starter drafts require distinct keys and terms.")
        return self


def load_starter_pack(path: Path = DEFAULT_PACK) -> LearningStarterPack:
    with path.open("rb") as stream:
        body = stream.read(1048577)
    if not 0 < len(body) <= 1048576:
        raise ValueError("The starter draft pack exceeds its byte budget.")
    return LearningStarterPack.model_validate_json(body)
