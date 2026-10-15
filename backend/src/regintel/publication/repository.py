"""Approved immutable manifests and atomic PostgreSQL authority/publication commits."""

import hashlib
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from regintel.auth.types import User
from regintel.candidates.records import stable_id
from regintel.contracts.models import TextEvidence
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, connect_database
from regintel.entities.models import canonical_bytes
from regintel.entities.repository import REGISTRY_LOCK_ID, EntityRepository, _snapshot
from regintel.publication.embeddings import RetrievalProjection
from regintel.publication.engine import (
    approve_candidate,
    build_manifest,
    require,
)
from regintel.publication.graph import GraphReceipt
from regintel.publication.models import (
    CorpusManifest,
    FilingSnapshot,
    PublicationConfiguration,
    PublicationRequest,
    PublishedObservation,
    ReviewedApproval,
)
from regintel.validation.models import ReviewDecision, ValidationInput, ValidationRun
from regintel.validation.repository import ValidationRepository, authorize, checked

PUBLICATION_LOCK_ID = 5928237198818004555


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def body(value: object, expected: object, *, maximum: int = 128000000) -> bytes:
    return checked(value, expected, maximum=maximum)


def persist_validation(
    connection: DatabaseConnection, source: ValidationInput, run: ValidationRun, user: User
) -> None:
    row = connection.execute(
        "SELECT run_bytes,run_sha256 FROM regintel.validation_runs WHERE id=%s", (run.id,)
    ).fetchone()
    if row is not None:
        require(body(row[0], row[1]) == canonical_bytes(run), "A sealed fresh gate conflicts.")
        return
    connection.execute(
        """INSERT INTO regintel.validation_runs
        (id,candidate_run_id,parse_version_id,input_bytes,input_sha256,configuration_bytes,
         configuration_sha256,run_bytes,run_sha256,result_count,submitted_by,auth_version)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            run.id,
            run.candidate_run_id,
            run.parse_version_id,
            canonical_bytes(source),
            run.input_sha256,
            canonical_bytes(run.configuration),
            run.configuration.sha256,
            canonical_bytes(run),
            digest(canonical_bytes(run)),
            len(run.results),
            user.id,
            user.auth_version,
        ),
    )


class PublicationRepository:
    def __init__(self, database: DatabaseSettings) -> None:
        self.database = database
        self.validator = ValidationRepository(database)

    @staticmethod
    def locks(connection: DatabaseConnection, user: User) -> None:
        authorize(connection, user)
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (PUBLICATION_LOCK_ID,))
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (REGISTRY_LOCK_ID,))
        ValidationRepository._snapshot_lock(connection)
        connection.execute("LOCK TABLE regintel.validation_reviews IN SHARE MODE")

    @staticmethod
    def _head(connection: DatabaseConnection) -> str | None:
        row = connection.execute(
            "SELECT corpus_version_id FROM regintel.publication_head"
        ).fetchone()
        return str(row[0]) if row is not None else None

    @staticmethod
    def _manifest(
        connection: DatabaseConnection, corpus_id: str, *, published: bool = False
    ) -> CorpusManifest:
        row = connection.execute(
            "SELECT b.manifest_bytes,b.manifest_sha256,v.state FROM regintel.publication_builds b "
            "JOIN regintel.corpus_versions v ON v.id=b.id WHERE b.id=%s",
            (UUID(corpus_id),),
        ).fetchone()
        require(
            row is not None and (not published or row[2] == "PUBLISHED"),
            "The requested approved corpus is unavailable.",
        )
        assert row is not None
        payload = body(row[0], row[1])
        manifest = CorpusManifest.model_validate_json(payload)
        require(
            canonical_bytes(manifest) == payload and manifest.id == corpus_id,
            "The approved manifest storage differs.",
        )
        return manifest

    def get_build(self, corpus_id: str, user: User) -> CorpusManifest:
        with connect_database(self.database) as connection, connection.transaction():
            authorize(connection, user)
            return self._manifest(connection, corpus_id)

    def published(self, corpus_id: str | None = None) -> CorpusManifest:
        with connect_database(self.database) as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            selected = corpus_id or self._head(connection)
            require(selected is not None, "No corpus is published.")
            assert selected is not None
            return self._manifest(connection, selected, published=True)

    def is_published(self, corpus_id: str) -> bool:
        with connect_database(self.database) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM regintel.publication_commits c "
                    "JOIN regintel.corpus_versions v ON v.id=c.corpus_version_id "
                    "WHERE v.id=%s AND v.state='PUBLISHED'",
                    (UUID(corpus_id),),
                ).fetchone()
                is not None
            )

    @staticmethod
    def _filing(
        connection: DatabaseConnection,
        *,
        parse_id: str | None = None,
        version_id: str | None = None,
    ) -> FilingSnapshot:
        row = connection.execute(
            """SELECT f.filing_id,f.id,p.id,b.sha256,f.document_type,f.published_on::TEXT
            FROM regintel.parse_versions p JOIN regintel.filing_versions f ON
            f.id=p.filing_version_id
            JOIN regintel.source_blobs b ON b.id=p.source_blob_id JOIN regintel.parse_artifacts a
            ON a.parse_version_id=p.id
            JOIN regintel.filing_jobs j ON j.id=a.job_id AND j.state='PARSED' AND
            j.parse_version_id=p.id
            WHERE (%s::uuid IS NULL OR p.id=%s::uuid) AND (%s::uuid IS NULL OR f.id=%s::uuid)""",
            (parse_id, parse_id, version_id, version_id),
        ).fetchall()
        require(len(row) == 1, "An unambiguous sealed original parse is required.")
        return FilingSnapshot.model_validate(
            dict(
                zip(
                    (
                        "filing_id",
                        "filing_version_id",
                        "parse_version_id",
                        "source_sha256",
                        "document_type",
                        "published_on",
                    ),
                    (str(value) if isinstance(value, UUID) else value for value in row[0]),
                    strict=True,
                )
            )
        )

    @staticmethod
    def _review(connection: DatabaseConnection, candidate_id: str) -> ReviewedApproval | None:
        row = connection.execute(
            "SELECT review_bytes,review_sha256,reviewed_by,auth_version "
            "FROM regintel.validation_reviews WHERE candidate_id=%s",
            (candidate_id,),
        ).fetchone()
        if row is None:
            return None
        return ReviewedApproval.model_validate(
            {
                "decision": ReviewDecision.model_validate_json(body(row[0], row[1])),
                "reviewed_by": str(row[2]),
                "auth_version": row[3],
            }
        )

    def _construct(
        self,
        connection: DatabaseConnection,
        request: PublicationRequest,
        configuration: PublicationConfiguration,
        user: User,
    ) -> tuple[CorpusManifest, str]:
        require(
            self._head(connection) == request.parent_corpus_version_id,
            "The published head changed; select a new request explicitly.",
        )
        parent = (
            self._manifest(connection, request.parent_corpus_version_id, published=True)
            if request.parent_corpus_version_id
            else None
        )
        registry = _snapshot(connection)
        corpus_id = stable_id(
            "corpus:"
            + request.idempotency_key
            + ":"
            + digest(canonical_bytes(request))
            + ":"
            + configuration.sha256
        )
        filings: dict[str, FilingSnapshot] = {}
        evidence: dict[str, TextEvidence] = {}
        acceptances = []
        dependencies: dict[str, object] = {
            "registry_sha256": registry.sha256,
            "sources": {},
            "reviews": {},
        }
        source_dependencies: dict[str, str] = {}
        review_dependencies: dict[str, object] = {}
        for selection in request.selections:
            source = self.validator._input(connection, selection.candidate_run_id)
            filing = self._filing(connection, parse_id=source.candidate_run.parse_version_id)
            filings[filing.filing_version_id] = filing
            evidence.update((item.id, item) for item in source.source.evidence)
            review = self._review(connection, selection.candidate_id)
            acceptance = approve_candidate(
                corpus_id, selection, source, filing, review, configuration
            )
            if review is not None:
                original = self.validator._get_run(connection, review.decision.validation_run_id)
                require(
                    original.candidate_run_id == selection.candidate_run_id,
                    "The original review belongs to another run.",
                )
            persist_validation(connection, source, acceptance.fresh_validation, user)
            acceptances.append(acceptance)
            source_dependencies[selection.candidate_run_id] = (
                acceptance.fresh_validation.input_sha256
            )
            review_dependencies[selection.candidate_id] = (
                review.model_dump(mode="json") if review else None
            )
        for lineage in request.lineages:
            declared = connection.execute(
                "SELECT declared_parent_filing_version_id FROM "
                "regintel.filing_versions WHERE id=%s",
                (lineage.child_filing_version_id,),
            ).fetchone()
            require(
                declared is not None
                and (declared[0] is None or str(declared[0]) == lineage.parent_filing_version_id),
                "A reviewed lineage conflicts with the explicit original parent.",
            )
            for version_id in (lineage.parent_filing_version_id, lineage.child_filing_version_id):
                if version_id not in filings:
                    filings[version_id] = self._filing(connection, version_id=version_id)
        # Reverify every source used by a lineage or effect against its sealed artifact.
        for effect in request.effects:
            links = (
                (*request.lineages, *(item.proposal for item in parent.lineages))
                if parent
                else request.lineages
            )
            effect_lineage = next((item for item in links if item.id == effect.lineage_id), None)
            require(effect_lineage is not None, "An explicit supported lineage is required.")
            assert effect_lineage is not None
            for version_id in (
                effect_lineage.parent_filing_version_id,
                effect_lineage.child_filing_version_id,
            ):
                if version_id not in filings:
                    filings[version_id] = self._filing(connection, version_id=version_id)
        entities = EntityRepository(self.database)
        # Existing helper verifies original job/artifact/configuration/projection bytes;
        # those immutable records can safely be read through its separate connection.
        for filing in filings.values():
            records, _ = entities.evidence_for_parse(filing.parse_version_id)
            evidence.update((item.id, item) for item in records)
        dependencies["sources"] = source_dependencies
        dependencies["reviews"] = review_dependencies
        manifest = build_manifest(
            request,
            configuration,
            user,
            tuple(acceptances),
            tuple(filings.values()),
            tuple(evidence.values()),
            registry,
            parent,
        )
        return manifest, digest(json_bytes(dependencies))

    def build(
        self, request: PublicationRequest, configuration: PublicationConfiguration, user: User
    ) -> CorpusManifest:
        request = PublicationRequest.model_validate(request.model_dump(mode="python"))
        with connect_database(self.database) as connection, connection.transaction():
            self.locks(connection, user)
            existing = connection.execute(
                "SELECT id,request_bytes,request_sha256,approved_by,auth_version "
                "FROM regintel.publication_builds WHERE idempotency_key=%s",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                require(
                    body(existing[1], existing[2]) == canonical_bytes(request)
                    and existing[3] == user.id
                    and existing[4] == user.auth_version,
                    "The immutable publication request conflicts.",
                )
                manifest = self._manifest(connection, str(existing[0]))
                require(
                    manifest.configuration == configuration,
                    "The original publication configuration differs.",
                )
                return manifest
            manifest, dependency_sha = self._construct(connection, request, configuration, user)
            connection.execute(
                """INSERT INTO regintel.publication_builds
                (id,idempotency_key,request_bytes,request_sha256,manifest_bytes,manifest_sha256,
                 dependency_sha256,approved_by,auth_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    manifest.id,
                    request.idempotency_key,
                    canonical_bytes(request),
                    manifest.request_sha256,
                    canonical_bytes(manifest),
                    manifest.sha256,
                    dependency_sha,
                    user.id,
                    user.auth_version,
                ),
            )
            connection.execute(
                """INSERT INTO regintel.corpus_versions
                (id, parent_corpus_version_id, state, configuration_sha256) VALUES(%s, %s,
                'BUILDING', %s)""",
                (manifest.id, manifest.parent_corpus_version_id, configuration.sha256),
            )
            return manifest

    def save_retrieval(self, projection: RetrievalProjection, user: User) -> None:
        with connect_database(self.database) as connection, connection.transaction():
            authorize(connection, user)
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (PUBLICATION_LOCK_ID,))
            manifest = self._manifest(connection, projection.corpus_version_id)
            require(projection.manifest_sha256 == manifest.sha256, "Retrieval approval differs.")
            existing = self._retrieval(connection, manifest.id)
            if existing is not None:
                require(
                    existing == projection, "A prepared immutable retrieval projection conflicts."
                )
                return
            connection.execute(
                """INSERT INTO regintel.publication_retrieval
                (corpus_version_id, projection_bytes, projection_sha256, chunk_count, prepared_by,
                auth_version)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (
                    manifest.id,
                    canonical_bytes(projection),
                    projection.sha256,
                    len(projection.chunks),
                    user.id,
                    user.auth_version,
                ),
            )
            self._chunks(connection, projection)

    @staticmethod
    def _chunks(connection: DatabaseConnection, projection: RetrievalProjection) -> None:
        for chunk in projection.chunks:
            connection.execute(
                """INSERT INTO regintel.retrieval_chunks
                (id,corpus_version_id,observation_id,evidence_id,start_offset,end_offset,quote,
                 token_count, embedding, term_counts) VALUES(%s, %s, %s, %s, %s, %s, %s, %s,
                 %s::public.vector, %s)""",
                (
                    chunk.id,
                    projection.corpus_version_id,
                    chunk.observation_id,
                    chunk.support.evidence_id,
                    chunk.support.start,
                    chunk.support.end,
                    chunk.support.quote,
                    chunk.token_count,
                    "[" + ",".join(str(value) for value in chunk.embedding) + "]",
                    Jsonb(chunk.term_counts),
                ),
            )

    @staticmethod
    def _retrieval(connection: DatabaseConnection, corpus_id: str) -> RetrievalProjection | None:
        row = connection.execute(
            "SELECT projection_bytes,projection_sha256 FROM regintel.publication_retrieval "
            "WHERE corpus_version_id=%s",
            (corpus_id,),
        ).fetchone()
        return RetrievalProjection.model_validate_json(body(row[0], row[1])) if row else None

    def retrieval(self, corpus_id: str, user: User) -> RetrievalProjection | None:
        with connect_database(self.database) as connection, connection.transaction():
            authorize(connection, user)
            return self._retrieval(connection, corpus_id)

    def rebuild_retrieval(self, corpus_id: str, user: User) -> None:
        with connect_database(self.database) as connection, connection.transaction():
            self.locks(connection, user)
            manifest = self._manifest(connection, corpus_id)
            projection = self._retrieval(connection, corpus_id)
            require(
                projection is not None and projection.manifest_sha256 == manifest.sha256,
                "A rebuild requires the immutable approved projection.",
            )
            assert projection is not None
            connection.execute(
                "INSERT INTO regintel.retrieval_rebuilds"
                "(id,corpus_version_id,rebuilt_by,auth_version) VALUES(%s,%s,%s,%s)",
                (uuid4(), corpus_id, user.id, user.auth_version),
            )
            connection.execute(
                "DELETE FROM regintel.retrieval_chunks WHERE corpus_version_id=%s", (corpus_id,)
            )
            self._chunks(connection, projection)
            self._verify_chunks(connection, projection)

    def save_graph(self, receipt: GraphReceipt, user: User) -> None:
        with connect_database(self.database) as connection, connection.transaction():
            authorize(connection, user)
            existing = connection.execute(
                "SELECT receipt_bytes,receipt_sha256 FROM regintel.publication_graph_receipts "
                "WHERE corpus_version_id=%s",
                (receipt.corpus_version_id,),
            ).fetchone()
            if existing:
                require(
                    body(existing[0], existing[1]) == canonical_bytes(receipt),
                    "An immutable graph receipt conflicts.",
                )
                return
            connection.execute(
                """INSERT INTO regintel.publication_graph_receipts
                (corpus_version_id, receipt_bytes, receipt_sha256, prepared_by, auth_version)
                VALUES(%s, %s, %s, %s, %s)""",
                (
                    receipt.corpus_version_id,
                    canonical_bytes(receipt),
                    digest(canonical_bytes(receipt)),
                    user.id,
                    user.auth_version,
                ),
            )

    def finalize(
        self,
        corpus_id: str,
        configuration: PublicationConfiguration,
        user: User,
        graph_receipt: GraphReceipt,
    ) -> CorpusManifest:
        with connect_database(self.database) as connection, connection.transaction():
            self.locks(connection, user)
            manifest = self._manifest(connection, corpus_id)
            existing = connection.execute(
                "SELECT 1 FROM regintel.publication_commits WHERE corpus_version_id=%s",
                (corpus_id,),
            ).fetchone()
            if existing is not None:
                return manifest
            require(
                manifest.configuration == configuration,
                "The installed publication configuration changed.",
            )
            row = connection.execute(
                "SELECT request_bytes,request_sha256,dependency_sha256 FROM "
                "regintel.publication_builds "
                "WHERE id=%s",
                (corpus_id,),
            ).fetchone()
            assert row is not None
            request = PublicationRequest.model_validate_json(body(row[0], row[1]))
            actual, dependency_sha = self._construct(connection, request, configuration, user)
            require(
                actual == manifest and dependency_sha == row[2],
                "Publication approval or current audited dependencies changed.",
            )
            projection = self._retrieval(connection, corpus_id)
            require(projection is not None, "The approved retrieval projection must be prepared.")
            assert projection is not None
            self._verify_chunks(connection, projection)
            require(
                graph_receipt.corpus_version_id == manifest.id
                and graph_receipt.manifest_sha256 == manifest.sha256,
                "The verified graph belongs to another publication.",
            )
            connection.execute(
                """INSERT INTO regintel.publication_commits
                (corpus_version_id,parent_corpus_version_id,manifest_sha256,retrieval_sha256,
                 graph_receipt_sha256,published_by,auth_version) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (
                    manifest.id,
                    manifest.parent_corpus_version_id,
                    manifest.sha256,
                    projection.sha256,
                    digest(canonical_bytes(graph_receipt)),
                    user.id,
                    user.auth_version,
                ),
            )
            for acceptance in manifest.new_acceptances:
                self._observation(connection, manifest, acceptance.observation, user)
            connection.execute(
                "UPDATE regintel.corpus_versions SET state='PUBLISHED' WHERE id=%s", (manifest.id,)
            )
            connection.execute(
                "INSERT INTO regintel.publication_head(singleton,corpus_version_id) "
                "VALUES(TRUE,%s) "
                "ON CONFLICT(singleton) DO UPDATE SET corpus_version_id=EXCLUDED.corpus_version_id",
                (manifest.id,),
            )
            return manifest

    @staticmethod
    def _verify_chunks(connection: DatabaseConnection, projection: RetrievalProjection) -> None:
        rows = connection.execute(
            "SELECT id,observation_id,evidence_id,start_offset,end_offset,quote,token_count,"
            "embedding::TEXT,term_counts FROM regintel.retrieval_chunks WHERE "
            "corpus_version_id=%s ORDER BY id",
            (projection.corpus_version_id,),
        ).fetchall()
        require(
            len(rows) == len(projection.chunks), "The stored retrieval projection is incomplete."
        )
        import json
        import struct

        for row, chunk in zip(rows, projection.chunks, strict=True):
            expected = (
                chunk.id,
                chunk.observation_id,
                chunk.support.evidence_id,
                chunk.support.start,
                chunk.support.end,
                chunk.support.quote,
                chunk.token_count,
            )
            actual = tuple(str(item) if isinstance(item, UUID) else item for item in row[:7])
            vectors = json.loads(str(row[7]))
            require(
                actual == expected
                and row[8] == chunk.term_counts
                and all(
                    struct.pack("f", a) == struct.pack("f", b)
                    for a, b in zip(vectors, chunk.embedding, strict=True)
                ),
                "Stored retrieval content differs from its approved projection.",
            )

    @staticmethod
    def _observation(
        connection: DatabaseConnection,
        manifest: CorpusManifest,
        observation: "PublishedObservation",
        user: User,
    ) -> None:
        value = observation.quantity
        context_id = stable_id("accepted-quantity:" + observation.id) if value is not None else None
        if value is not None:
            connection.execute(
                """INSERT INTO regintel.quantitative_contexts
                (id, parse_version_id, raw_value, normalized_value, raw_unit, normalized_unit,
                raw_currency, currency,
                 period_kind, start_date, end_date, instant_date, raw_period_label, basis,
                 raw_basis_label,
                 denominator, stake_kind, ownership_date, evidence_count) VALUES(%s, %s, %s, %s,
                 %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    context_id,
                    observation.parse_version_id,
                    value.raw_value,
                    value.normalized_value,
                    value.raw_unit,
                    value.normalized_unit,
                    value.raw_currency,
                    value.currency,
                    value.period.kind,
                    value.period.start_date,
                    value.period.end_date,
                    value.period.instant_date,
                    value.period.raw_label,
                    value.basis,
                    value.raw_basis_label,
                    value.denominator,
                    value.stake_kind,
                    value.ownership_date,
                    len(value.evidence_ids),
                ),
            )
            for evidence_id in value.evidence_ids:
                connection.execute(
                    "INSERT INTO "
                    "regintel.quantitative_context_evidence"
                    "(context_id,parse_version_id,evidence_id) "
                    "VALUES(%s,%s,%s)",
                    (context_id, observation.parse_version_id, evidence_id),
                )
        connection.execute(
            """INSERT INTO regintel.acceptance_audits
            (id,candidate_id,parse_version_id,actor_user_id,decision,validator_configuration_sha256)
            VALUES(%s,%s,%s,%s,'ACCEPTED',%s)""",
            (
                observation.acceptance_audit_id,
                observation.candidate_id,
                observation.parse_version_id,
                user.id,
                observation.validator_configuration_sha256,
            ),
        )
        if observation.kind == "relation":
            connection.execute(
                """INSERT INTO regintel.relation_observations
                (id, candidate_id, parse_version_id, acceptance_audit_id, corpus_version_id,
                subject_entity_id,
                 object_entity_id, relation_type, quantitative_context_id) VALUES(%s, %s, %s, %s,
                 %s, %s, %s, %s, %s)""",
                (
                    observation.id,
                    observation.candidate_id,
                    observation.parse_version_id,
                    observation.acceptance_audit_id,
                    manifest.id,
                    observation.subject_entity_id,
                    observation.object_entity_id,
                    observation.relation_type,
                    context_id,
                ),
            )
        else:
            connection.execute(
                """INSERT INTO regintel.fact_observations
                (id, candidate_id, parse_version_id, acceptance_audit_id, corpus_version_id, kind,
                subject_entity_id,
                 metric_id, quantitative_context_id, raw_text) VALUES(%s, %s, %s, %s, %s, %s, %s,
                 %s, %s, %s)""",
                (
                    observation.id,
                    observation.candidate_id,
                    observation.parse_version_id,
                    observation.acceptance_audit_id,
                    manifest.id,
                    observation.kind,
                    observation.subject_entity_id,
                    observation.metric_id,
                    context_id,
                    observation.raw_text,
                ),
            )
        payload = canonical_bytes(observation)
        connection.execute(
            """INSERT INTO regintel.publication_observations
            (id, candidate_id, first_corpus_version_id, observation_bytes, observation_sha256,
            normalized_value)
            VALUES(%s,%s,%s,%s,%s,%s)""",
            (
                observation.id,
                observation.candidate_id,
                manifest.id,
                payload,
                digest(payload),
                value.normalized_value if value else None,
            ),
        )


def json_bytes(value: dict[str, object]) -> bytes:
    import json

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
