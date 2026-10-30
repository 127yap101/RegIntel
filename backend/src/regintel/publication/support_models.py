"""Versioned amendment supports retain separate original spans, never a joined quote."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.candidates.models import SourceSpan
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId


class NativeAmendmentWords(ContractModel):
    schema_version: Literal["native-amendment-words-1"]
    parse_version_id: CanonicalId
    spans: Annotated[tuple[SourceSpan, ...], Field(strict=False, min_length=1, max_length=128)]

    @model_validator(mode="after")
    def complete_bounded_words(self) -> Self:
        if (
            len({span.evidence_id for span in self.spans}) != len(self.spans)
            or any(span.start != 0 or span.end != len(span.quote) for span in self.spans)
            or sum(len(span.quote) for span in self.spans) > 20_000
        ):
            raise ValueError(
                "Native amendment support needs distinct bounded whole original words."
            )
        return self


type AmendmentSupport = SourceSpan | NativeAmendmentWords
