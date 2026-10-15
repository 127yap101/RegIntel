"""Published-view isolation and source ownership using labelled authored inputs."""

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_entity_api import Users
from test_evidence_api import DATA, EvidenceMemory
from test_publication_engine import ALPHA, BETA, administrator, authored, create

from backend.tests.evidence_fixtures import synthetic_artifact
from regintel.auth.config import AuthSettings
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.entities.models import EntityRegistration, EvidenceAnchor
from regintel.evidence.api import EvidenceService
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.models import SourceBlob
from regintel.ingestion.storage import SourceStorage
from regintel.main import create_app
from regintel.publication.engine import PublicationConflict
from regintel.publication.graph import GraphReceipt, GraphUnavailable, graph_data
from regintel.publication.models import CorpusManifest
from regintel.reads.repository import Catalog
from regintel.reads.service import PublishedReadService


class FrozenMemory:
    def __init__(self, manifest: CorpusManifest, catalog: Catalog) -> None:
        self.manifest = manifest
        self.value = catalog
        self.calls: list[str] = []
        self.unpublished = False

    def published(self, corpus_id: str | None = None) -> CorpusManifest:
        self.calls.append("published")
        if self.unpublished or corpus_id not in (None, self.manifest.id):
            raise PublicationConflict("Private unfinished manifest.")
        return self.manifest

    def catalog(self, manifest: CorpusManifest) -> Catalog:
        self.calls.append("catalog")
        assert manifest == self.manifest
        return self.value


class VerifiedGraph:
    def __init__(self) -> None:
        self.calls = 0
        self.unavailable = False

    def prepare(self, manifest: CorpusManifest) -> GraphReceipt:
        raise AssertionError("Consumer reads cannot write graph projections.")

    def verify(self, manifest: CorpusManifest) -> GraphReceipt:
        self.calls += 1
        if self.unavailable:
            raise GraphUnavailable("Private graph diagnostic.")
        data = graph_data(manifest)
        return GraphReceipt(
            namespace="regintel",
            corpus_version_id=manifest.id,
            manifest_sha256=manifest.sha256,
            graph_sha256=data.sha256,
            node_count=len(data.nodes),
            edge_count=len(data.edges),
        )


def fixture_service(
    tmp_path: Path,
) -> tuple[PublishedReadService, FrozenMemory, EvidenceMemory, VerifiedGraph]:
    source = authored(f"{ALPHA} supplies to {BETA}.")
    manifest = create(source)
    sha = hashlib.sha256(DATA).hexdigest()
    manifest = manifest.model_copy(
        update={"filings": (manifest.filings[0].model_copy(update={"source_sha256": sha}),)}
    )
    record = source.source.evidence[0]
    names = (
        (source.source.entity_run.mentions[0].resolution.entity_id, ALPHA),
        (source.source.entity_run.mentions[1].resolution.entity_id, BETA),
    )
    entities = []
    for identity, name in names:
        assert identity is not None
        start = record.span.start + record.span.quote.index(name)
        entities.append(
            EntityRegistration(
                id=identity,
                kind="COMPANY",
                legal_name=name,
                legal_name_support=EvidenceAnchor(
                    evidence_id=record.id, start=start, end=start + len(name), quote=name
                ),
                review_note="Authored reviewed identity.",
            )
        )
    catalog = Catalog(entities=tuple(entities), metrics=source.source.metrics)
    memory = FrozenMemory(manifest, catalog)
    storage = SourceStorage(
        IngestionSettings(
            source_root=tmp_path / "sources",
            broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0"),
        )
    )
    blob = SourceBlob(
        id=str(uuid4()), sha256=sha, byte_size=len(DATA), storage_key=f"sha256/{sha}.pdf"
    )
    (storage.root / blob.storage_key).write_bytes(DATA)
    evidence = EvidenceMemory(blob, record, synthetic_artifact().provenance)
    graph = VerifiedGraph()
    return (
        PublishedReadService(memory, memory, EvidenceService(evidence, storage), graph),
        memory,
        evidence,
        graph,
    )


@pytest.mark.parametrize(
    "endpoint", ["current", "companies", "facts", "graph", "evidence", "pdf", "head"]
)
@pytest.mark.parametrize("role", ["anonymous", "learner", "admin"])
def test_reader_auth_version_and_published_membership(
    tmp_path: Path, endpoint: str, role: str
) -> None:
    service, memory, evidence, graph = fixture_service(tmp_path)
    observation = memory.manifest.observations[0]
    corpus = memory.manifest.id
    company = observation.subject_entity_id
    prefix = f"/v1/corpora/{corpus}/observations/{observation.id}"
    path = {
        "current": "/v1/published-corpus",
        "companies": "/v1/companies",
        "facts": f"/v1/companies/{company}/facts",
        "graph": f"/v1/companies/{company}/graph",
        "evidence": prefix + "/evidence/" + observation.supports[0].evidence_id,
        "pdf": prefix + "/source.pdf",
        "head": prefix + "/source.pdf",
    }[endpoint]
    user = replace(administrator(), role="learner") if role == "learner" else administrator()
    settings = AuthSettings(jwt_secret=SecretStr("ab" * 32))
    auth = AuthService(Users(user), settings)
    headers = (
        {} if role == "anonymous" else {"Authorization": "Bearer " + issue_token(user, settings)}
    )
    with TestClient(create_app(auth_service=auth, read_service=service)) as client:
        result = client.request("HEAD" if endpoint == "head" else "GET", path, headers=headers)
    assert result.status_code == (401 if role == "anonymous" else 200)
    if role == "anonymous":
        assert memory.calls == [] and evidence.calls == [] and graph.calls == 0
    elif endpoint in {"pdf", "head"}:
        assert result.headers["x-corpus-version-id"] == corpus
        assert result.content == (b"" if endpoint == "head" else DATA)
    else:
        assert result.json()["meta"]["versions"]["corpus_version_id"] == corpus
        assert (
            result.json()["data"].get("view", result.json()["data"])["corpus_version_id"] == corpus
        )


def client_for(service: PublishedReadService) -> tuple[TestClient, dict[str, str], Users]:
    user = replace(administrator(), role="learner")
    users = Users(user)
    settings = AuthSettings(jwt_secret=SecretStr("ab" * 32))
    return (
        TestClient(create_app(auth_service=AuthService(users, settings), read_service=service)),
        {"Authorization": "Bearer " + issue_token(user, settings)},
        users,
    )


def test_unpublished_unknown_and_cross_observation_sources_deny_before_lookup(
    tmp_path: Path,
) -> None:
    service, memory, evidence, graph = fixture_service(tmp_path)
    observation = memory.manifest.observations[0]
    with client_for(service)[0] as client:
        headers = client_for(service)[1]
        memory.unpublished = True
        result = client.get("/v1/companies", headers=headers)
        assert result.status_code == 404
        memory.unpublished = False
        result = client.get(
            "/v1/companies", params={"corpus_version_id": str(uuid4())}, headers=headers
        )
        assert result.status_code == 404
        base = f"/v1/corpora/{memory.manifest.id}/observations/"
        assert client.get(base + str(uuid4()) + "/source.pdf", headers=headers).status_code == 404
        assert (
            client.get(
                base + observation.id + "/evidence/" + str(uuid4()), headers=headers
            ).status_code
            == 404
        )
    assert evidence.calls == [] and graph.calls == 0


def test_pagination_literal_search_and_graph_direction(tmp_path: Path) -> None:
    service, memory, _, graph = fixture_service(tmp_path)
    scope = service.scope(None)
    first = service.companies(scope, "energy", 0, 1)
    assert first.total == 1 and first.companies[0].name == ALPHA
    assert service.companies(scope, "%", 0, 25).total == 0
    assert service.companies(scope, "", 1, 1).total == 2
    assert len(service.companies(scope, "", 1, 1).companies) == 1
    assert service.companies(scope, "", 3, 1).companies == ()
    observation = scope.view.observations[0]
    view = service.company_graph(scope, observation.subject_entity_id)
    assert view.edges == (observation,)
    assert view.edges[0].object_entity_id != view.edges[0].subject_entity_id
    assert len(view.nodes) == 2 and graph.calls == 1


def test_inactive_and_unknown_date_never_look_active(tmp_path: Path) -> None:
    service, memory, evidence, _ = fixture_service(tmp_path)
    observation = memory.manifest.observations[0]
    memory.manifest = memory.manifest.model_copy(update={"active_observation_ids": ()})
    assert service.companies(service.scope(None), "", 0, 25).total == 0
    assert service.company_graph(
        service.scope(None, historical=True), observation.subject_entity_id
    ).edges
    memory.manifest = memory.manifest.model_copy(
        update={"filings": (memory.manifest.filings[0].model_copy(update={"published_on": None}),)}
    )
    scope = service.scope(None, "2026-01-01")
    assert scope.info.state == "TEMPORAL_SUPPORT_UNAVAILABLE"
    assert service.companies(scope, "", 0, 25).companies == ()
    assert service.company_graph(scope, observation.subject_entity_id).edges == ()
    with client_for(service)[0] as client:
        headers = client_for(service)[1]
        base = f"/v1/corpora/{memory.manifest.id}/observations/{observation.id}/source.pdf"
        assert client.get(base, headers=headers).status_code == 404
        assert client.get(base + "?historical=true", headers=headers).status_code == 200
    assert evidence.calls == ["source"]


@pytest.mark.parametrize(
    "kind", ["wrong_quote", "wrong_source", "wrong_parse", "graph_down", "revoked"]
)
def test_corruption_outage_and_revocation_fail_closed(tmp_path: Path, kind: str) -> None:
    service, memory, evidence, graph = fixture_service(tmp_path)
    observation = memory.manifest.observations[0]
    client, headers, users = client_for(service)
    path = (
        f"/v1/corpora/{memory.manifest.id}/observations/{observation.id}/evidence/"
        + observation.supports[0].evidence_id
    )
    assert evidence.result is not None
    record, provenance, sha, processing = evidence.result
    if kind == "wrong_quote":
        record = record.model_copy(
            update={"span": record.span.model_copy(update={"quote": "x" * len(record.span.quote)})}
        )
    if kind == "wrong_source":
        sha = "0" * 64
    if kind == "wrong_parse":
        record = record.model_copy(
            update={"source": record.source.model_copy(update={"parse_version_id": str(uuid4())})}
        )
    evidence.result = (record, provenance, sha, processing)
    if kind == "graph_down":
        graph.unavailable = True
        path = f"/v1/companies/{observation.subject_entity_id}/graph"
    if kind == "revoked":
        users.user = replace(administrator(), role="learner", auth_version=2)
    with client:
        result = client.get(path, headers=headers)
    assert result.status_code == (401 if kind == "revoked" else 503)
    assert "private" not in result.text.lower()
    if kind == "revoked":
        assert memory.calls == [] and evidence.calls == []


def test_published_pdf_range_conditional_and_revoked_304(tmp_path: Path) -> None:
    service, memory, _, _ = fixture_service(tmp_path)
    observation = memory.manifest.observations[0]
    client, headers, users = client_for(service)
    path = f"/v1/corpora/{memory.manifest.id}/observations/{observation.id}/source.pdf"
    with client:
        partial = client.get(path, headers={**headers, "Range": "bytes=2-9"})
        assert partial.status_code == 206 and partial.content == DATA[2:10]
        assert partial.headers["content-range"] == f"bytes 2-9/{len(DATA)}"
        etag = partial.headers["etag"]
        assert client.get(path, headers={**headers, "If-None-Match": etag}).status_code == 304
        assert (
            client.get(path, headers={**headers, "Range": f"bytes={len(DATA)}-"}).status_code == 416
        )
        users.user = replace(administrator(), role="learner", auth_version=2)
        assert client.get(path, headers={**headers, "If-None-Match": etag}).status_code == 401
