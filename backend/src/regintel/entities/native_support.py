"""Inspect native identity support without creating a combined quotation or evidence."""

from regintel.contracts.models import TextEvidence
from regintel.entities.models import NativeCompanyRegistration
from regintel.parsing.models import ParseArtifact
from regintel.publication.support import native_word_index


def verify_native_company(
    registration: NativeCompanyRegistration,
    artifact: ParseArtifact,
    evidence: tuple[TextEvidence, ...],
) -> None:
    registration = NativeCompanyRegistration.model_validate(registration.model_dump(mode="python"))
    positions = native_word_index(artifact, evidence)
    for phrase in (registration.legal_name_support, registration.issuer_header):
        if phrase.parse_version_id != artifact.id:
            raise ValueError("Native identity support differs from its sealed parse.")
        first = positions.get(phrase.spans[0].evidence_id)
        if first is None:
            raise ValueError("Native identity support needs original native word positions.")
        for offset, span in enumerate(phrase.spans):
            position = positions.get(span.evidence_id)
            if (
                position is None
                or not position.complete
                or position.index != first.index + offset
                or position.evidence.source != first.evidence.source
                or position.evidence.span.start != span.start
                or position.evidence.span.end != span.end
                or position.evidence.span.quote != span.quote
            ):
                raise ValueError("Native identity support cannot change original words/order/page.")
