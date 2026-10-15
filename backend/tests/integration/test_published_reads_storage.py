"""Real read-only PG catalog checks against explicitly authored published sources."""

from pathlib import Path
from uuid import uuid4

import pytest

from backend.tests.integration.test_publication_storage import (
    configuration,
    prepared,
)
from backend.tests.integration.test_publication_storage import (
    publication as publication,
)
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.auth.types import User
from regintel.db.migrations import connect_database
from regintel.evidence.api import EvidenceService
from regintel.evidence.repository import EvidenceRepository
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.storage import SourceStorage
from regintel.publication.models import PublicationRequest
from regintel.publication.repository import PublicationRepository
from regintel.reads.repository import ReadNotFound, ReadRepository, ReadUnavailable
from regintel.reads.service import PublishedReadService

pytestmark = pytest.mark.integration


def service(repository: PublicationRepository, tmp_path: Path) -> PublishedReadService:
    from pydantic import SecretStr

    return PublishedReadService(
        repository,
        ReadRepository(repository.database),
        EvidenceService(
            EvidenceRepository(repository.database),
            SourceStorage(
                IngestionSettings(
                    source_root=tmp_path / "sources",
                    broker_url=SecretStr("redis://:authored@127.0.0.1:6379/0"),
                )
            ),
        ),
        None,
    )


@pytest.mark.parametrize(
    "scenario", ["positive", "unpublished", "new_head", "changed_fingerprint", "source_membership"]
)
def test_frozen_published_catalog_and_decimal_context(
    publication: tuple[PublicationRepository, User, PublicationRequest],
    tmp_path: Path,
    scenario: str,
) -> None:
    repository, user, request = publication
    all_selections = request.selections
    if scenario == "new_head":
        request = request.model_copy(update={"selections": all_selections[:1]})
    manifest = repository.build(request, configuration(), user)
    reader = service(repository, tmp_path)
    if scenario == "unpublished":
        with pytest.raises(ReadNotFound):
            reader.scope(manifest.id)
        return
    repository.finalize(manifest.id, configuration(), user, prepared(repository, user, manifest))
    scope = reader.scope(manifest.id)
    if scenario == "new_head":
        old_companies = reader.companies(scope, "", 0, 25)
        other = repository.build(
            request.model_copy(
                update={
                    "idempotency_key": str(uuid4()),
                    "parent_corpus_version_id": manifest.id,
                    "selections": all_selections[1:],
                }
            ),
            configuration(),
            user,
        )
        repository.finalize(other.id, configuration(), user, prepared(repository, user, other))
        assert len(reader.scope(None).view.observations) == 3
        assert reader.scope(None).manifest.id == other.id
        assert reader.scope(manifest.id).manifest == manifest
        assert len(reader.scope(manifest.id).view.observations) == 1
        assert reader.companies(scope, "", 0, 25) == old_companies
        return
    catalog = reader.catalog.catalog(manifest)
    assert len(catalog.entities) == 2 and len(catalog.metrics) == 2
    result = reader.companies(scope, "solar", 0, 1)
    assert result.total == 2 and len(result.companies) == 1
    assert reader.companies(scope, "%' OR TRUE --", 0, 25).total == 0
    company = next(item for item in catalog.entities if item.legal_name.startswith("Alpha"))
    facts = reader.facts(scope, company.id, 0, 25)
    assert facts.total == 2
    numeric = next(item for item in facts.facts if item.observation.quantity is not None)
    assert numeric.observation.quantity is not None
    wire = numeric.observation.quantity.model_dump(mode="json")
    assert wire["normalized_value"] == "1234.50" and wire["normalized_unit"] == "crore"
    assert wire["basis"] == "CONSOLIDATED" and wire["currency"] == "INR"
    assert reader.facts(scope, company.id, 1, 1).total == 2
    assert len(reader.facts(scope, company.id, 1, 1).facts) == 1
    assert (
        reader.companies(reader.scope(manifest.id, "2026-01-01"), "", 0, 25).view.state
        == "TEMPORAL_SUPPORT_UNAVAILABLE"
    )
    if scenario == "changed_fingerprint":
        altered = manifest.model_copy(
            update={
                "observations": tuple(
                    item.model_copy(update={"validation_input_sha256": "0" * 64})
                    for item in manifest.observations
                )
            }
        )
        with pytest.raises(ReadUnavailable):
            reader.catalog.catalog(altered)
    elif scenario == "source_membership":
        observation = numeric.observation
        evidence = reader.published_evidence(
            scope, observation.id, observation.supports[0].evidence_id
        )
        assert (
            evidence.supports
            and evidence.evidence.record.source.parse_version_id == observation.parse_version_id
        )
        with pytest.raises(ReadNotFound):
            reader.published_evidence(scope, observation.id, str(uuid4()))
    with connect_database(repository.database) as connection:
        assert connection.execute("SELECT count(*) FROM regintel.fact_observations").fetchone() == (
            2,
        )
