"""Recoverable projection preparation with final fresh PostgreSQL publication gates."""

import hashlib
from pathlib import Path

from regintel.auth.types import User
from regintel.publication.embeddings import (
    CpuBgeEncoder,
    TextEncoder,
    manifest_sha256,
    project_retrieval,
)
from regintel.publication.engine import require
from regintel.publication.graph import GraphProjection
from regintel.publication.models import CorpusManifest, PublicationConfiguration, PublicationRequest
from regintel.publication.repository import PublicationRepository
from regintel.validation.gate import current_configuration as validator_configuration


def current_configuration(model_root: Path) -> PublicationConfiguration:
    source_root = Path(__file__).resolve().parent
    source_files = sorted(source_root.glob("*.py"))
    identity = hashlib.sha256()
    for file in source_files:
        identity.update(file.name.encode() + b"\0" + file.read_bytes() + b"\0")
    return PublicationConfiguration(
        code_sha256=identity.hexdigest(),
        validator_configuration_sha256=validator_configuration().sha256,
        embedding_manifest_sha256=manifest_sha256(model_root),
    )


class PublicationService:
    def __init__(
        self,
        repository: PublicationRepository,
        graph: GraphProjection,
        configuration: PublicationConfiguration,
        *,
        encoder: TextEncoder | None = None,
        model_root: Path | None = None,
    ) -> None:
        self.repository = repository
        self.graph = graph
        self.configuration = configuration
        self.encoder = encoder
        self.model_root = model_root

    def _current(self) -> PublicationConfiguration:
        if self.model_root is not None:
            require(
                current_configuration(self.model_root) == self.configuration,
                "Installed publication source, validator or model configuration changed.",
            )
        return self.configuration

    def build(self, request: PublicationRequest, user: User) -> CorpusManifest:
        return self.repository.build(request, self._current(), user)

    def publish(self, corpus_id: str, user: User) -> CorpusManifest:
        manifest = self.repository.get_build(corpus_id, user)
        if self.repository.is_published(corpus_id):
            return manifest
        require(
            manifest.configuration == self._current(),
            "The approved publication configuration differs.",
        )
        projection = self.repository.retrieval(corpus_id, user)
        if projection is None:
            if self.encoder is None:
                require(self.model_root is not None, "The pinned CPU encoder is unavailable.")
                assert self.model_root is not None
                self.encoder = CpuBgeEncoder(
                    self.model_root, self.configuration.embedding_manifest_sha256
                )
            projection = project_retrieval(manifest, self.encoder)
            self.repository.save_retrieval(projection, user)
        receipt = self.graph.prepare(manifest)
        self.repository.save_graph(receipt, user)
        # Verify the actual complete projection again, including after recovery.
        require(self.graph.verify(manifest) == receipt, "The graph changed during preparation.")
        return self.repository.finalize(corpus_id, self._current(), user, receipt)

    def rebuild(self, corpus_id: str, user: User) -> CorpusManifest:
        manifest = self.repository.get_build(corpus_id, user)
        self.repository.rebuild_retrieval(corpus_id, user)
        receipt = self.graph.prepare(manifest)
        self.repository.save_graph(receipt, user)
        return manifest
