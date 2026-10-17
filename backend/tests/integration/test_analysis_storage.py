"""M2 reads actual published PostgreSQL state using explicitly authored filings."""

from decimal import Decimal
from pathlib import Path

import pytest

from backend.tests.integration.test_publication_storage import configuration, counts, prepared
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_published_reads_storage import service
from backend.tests.integration.test_validation_storage import SOURCE
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.analysis.models import ComparisonRequest
from regintel.analysis.service import ComparisonService
from regintel.auth.types import User
from regintel.publication.models import PublicationRequest
from regintel.publication.repository import PublicationRepository
from regintel.reads.repository import ReadNotFound

pytestmark = pytest.mark.integration

AUTHORED_SOURCE = SOURCE.replace("1,234.50", "1.00").replace(
    "Alpha Solar Limited business",
    "Beta Solar Limited revenue was INR 15.00 million on a consolidated basis "
    "from 1 April 2023 to 31 March 2024.\nAlpha Solar Limited business",
)


@pytest.mark.parametrize(
    "validated",
    [{"source": AUTHORED_SOURCE, "allowed_unit_labels": ("crore", "million")}],
    indirect=True,
)
@pytest.mark.parametrize("scenario", ["positive", "unpublished", "temporal", "different_period"])
def test_comparison_over_frozen_postgresql_inputs(
    publication: tuple[PublicationRepository, User, PublicationRequest],
    tmp_path: Path,
    scenario: str,
) -> None:
    repository, user, publication_request = publication
    manifest = repository.build(publication_request, configuration(), user)
    reads = service(repository, tmp_path)
    numeric = [item for item in manifest.observations if item.kind == "numeric_fact"]
    assert len(numeric) == 2
    alpha = next(item for item in numeric if "Alpha Solar Limited revenue" in item.raw_text)
    beta = next(item for item in numeric if "Beta Solar Limited revenue" in item.raw_text)
    assert alpha.quantity is not None and alpha.metric_id is not None
    request = ComparisonRequest(
        corpus_version_id=manifest.id,
        company_ids=(alpha.subject_entity_id, beta.subject_entity_id),
        metric_ids=(alpha.metric_id,),
        period=alpha.quantity.period,
        basis="CONSOLIDATED",
    )
    if scenario == "unpublished":
        with pytest.raises(ReadNotFound):
            ComparisonService(reads).compare(request)
        assert counts(repository) == (0, 0, 0, 0)
        return
    repository.finalize(manifest.id, configuration(), user, prepared(repository, user, manifest))
    before = counts(repository)
    if scenario == "temporal":
        request = request.model_copy(update={"as_of_date": "2026-01-01"})
    elif scenario == "different_period":
        request = request.model_copy(
            update={
                "period": request.period.model_copy(
                    update={
                        "start_date": "2022-04-01",
                        "end_date": "2023-03-31",
                    }
                )
            }
        )
    result = ComparisonService(reads).compare(request)
    row = result.rows[0]
    if scenario == "positive":
        assert all(cell.state == "AVAILABLE" for cell in row.cells)
        assert row.cells[0].normalized is not None and row.cells[1].normalized is not None
        assert row.cells[0].normalized.value == Decimal("10000000.00")
        assert row.cells[1].normalized.value == Decimal("15000000.00")
        assert row.differences[0].difference == Decimal("5000000.00")
        assert row.differences[0].percentage_difference == Decimal("50.000000")
        assert row.differences[0].input_observation_ids == (alpha.id, beta.id)
        assert row.cells[0].inputs[0].observation == alpha
        assert row.cells[1].inputs[0].observation == beta
    else:
        expected = "TEMPORAL_SUPPORT_UNAVAILABLE" if scenario == "temporal" else "INCOMPATIBLE"
        assert all(cell.state == expected and cell.normalized is None for cell in row.cells)
        assert row.differences[0].difference is None
    assert ComparisonService(reads).compare(request) == result
    assert counts(repository) == before
    assert repository.published(manifest.id).sha256 == manifest.sha256
