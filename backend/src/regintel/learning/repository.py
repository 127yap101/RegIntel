"""M3 append-only drafts/reviews and atomic independently versioned publication."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg

from regintel.auth.types import User
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, MigrationError, connect_database
from regintel.entities.models import canonical_bytes
from regintel.learning.draft_pack import LearningStarterPack, load_starter_pack
from regintel.learning.examples import calculate_example
from regintel.learning.models import (
    DefinitionDraft,
    DefinitionQueue,
    DefinitionQueueItem,
    DraftFilter,
    GlossaryVersion,
    LearningOverview,
    LearningReview,
    PublishLearning,
    ReviewedDefinition,
    StoredDefinition,
)


class LearningError(ValueError):
    """Safe module-owned diagnostic; no raw database or submitted content."""


class LearningForbidden(LearningError):
    pass


class LearningNotFound(LearningError):
    pass


class LearningConflict(LearningError):
    pass


class LearningUnavailable(LearningError):
    pass


def _bytes(value: object, sha: object) -> bytes:
    if not isinstance(value, (bytes, memoryview)):
        raise LearningUnavailable("Learning storage is invalid.")
    body = bytes(value)
    if not 0 < len(body) <= 2 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != sha:
        raise LearningUnavailable("Learning storage differs from its immutable fingerprint.")
    return body


class LearningRepository:
    def __init__(self, database: DatabaseSettings) -> None:
        self.database = database

    @contextmanager
    def transaction(
        self, user: User, *, admin: bool = False, consistent: bool = False
    ) -> Iterator[DatabaseConnection]:
        try:
            with connect_database(self.database) as connection, connection.transaction():
                if consistent:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                row = connection.execute(
                    "SELECT role,is_active,auth_version FROM regintel.users WHERE id=%s FOR SHARE",
                    (user.id,),
                ).fetchone()
                if row != (user.role, True, user.auth_version) or (admin and user.role != "admin"):
                    raise LearningForbidden("A current authorized learning account is required.")
                yield connection
        except LearningError:
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            MigrationError,
            psycopg.errors.UndefinedTable,
        ):
            raise LearningUnavailable("Reviewed learning storage is unavailable.") from None
        except (psycopg.Error, ValueError, OSError):
            raise LearningConflict(
                "The learning operation could not commit its complete result."
            ) from None

    def propose(self, draft: DefinitionDraft, user: User) -> StoredDefinition:
        draft = DefinitionDraft.model_validate(draft.model_dump(mode="python"))
        calculation = calculate_example(draft.example) if draft.example else None
        if calculation is not None and calculation.state != "AVAILABLE":
            raise LearningConflict("Resolve unavailable example inputs before review.")
        content = json.dumps(
            {
                "draft": draft.model_dump(mode="json"),
                "calculation": calculation.model_dump(mode="json") if calculation else None,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        result = StoredDefinition(
            id=str(uuid4()),
            content_sha256=hashlib.sha256(content).hexdigest(),
            draft=draft,
            calculation=calculation,
            submitted_by=str(user.id),
        )
        body = canonical_bytes(result)
        with self.transaction(user, admin=True) as connection:
            connection.execute(
                "INSERT INTO regintel.learning_definitions "
                "(id,payload,payload_sha256,submitted_by,auth_version) VALUES (%s,%s,%s,%s,%s)",
                (
                    UUID(result.id),
                    body,
                    hashlib.sha256(body).hexdigest(),
                    user.id,
                    user.auth_version,
                ),
            )
        return result

    def _definition(self, connection: DatabaseConnection, identity: str) -> StoredDefinition:
        row = connection.execute(
            "SELECT payload,payload_sha256 FROM regintel.learning_definitions WHERE id=%s",
            (UUID(identity),),
        ).fetchone()
        if row is None:
            raise LearningNotFound("The selected definition draft is unavailable.")
        body = _bytes(row[0], row[1])
        stored = StoredDefinition.model_validate_json(body)
        if stored.id != identity or canonical_bytes(stored) != body:
            raise LearningUnavailable("The selected learning draft differs from stored history.")
        expected = calculate_example(stored.draft.example) if stored.draft.example else None
        if stored.calculation != expected:
            raise LearningUnavailable(
                "Stored learning arithmetic differs from its deterministic inputs."
            )
        return stored

    def draft(self, identity: str, user: User) -> StoredDefinition:
        with self.transaction(user, admin=True) as connection:
            return self._definition(connection, identity)

    def starter_pack(self, user: User) -> LearningStarterPack:
        with self.transaction(user, admin=True):
            try:
                return load_starter_pack()
            except (OSError, ValueError):
                raise LearningUnavailable(
                    "Unreviewed learning starter drafts are unavailable."
                ) from None

    def queue(
        self,
        user: User,
        *,
        state: DraftFilter = "PENDING_REVIEW",
        query: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> DefinitionQueue:
        if (
            state not in {"ALL", "PENDING_REVIEW", "APPROVED", "REJECTED"}
            or not isinstance(query, str)
            or len(query) > 120
            or "\x00" in query
            or type(offset) is not int
            or not 0 <= offset <= 1000000
            or type(limit) is not int
            or not 1 <= limit <= 20
        ):
            raise LearningConflict("Select a bounded draft queue and literal term search.")
        with self.transaction(user, admin=True, consistent=True) as connection:
            condition = (
                "FROM regintel.learning_definitions d LEFT JOIN regintel.learning_reviews r "
                "ON r.definition_id=d.id WHERE "
                "(%s='ALL' OR (%s='PENDING_REVIEW' AND r.id IS NULL) OR "
                "(%s='APPROVED' AND "
                "convert_from(r.review_bytes,'UTF8')::jsonb->>'decision'='APPROVE') OR "
                "(%s='REJECTED' AND "
                "convert_from(r.review_bytes,'UTF8')::jsonb->>'decision'='REJECT')) "
                "AND position(lower(%s) in "
                "lower(convert_from(d.payload,'UTF8')::jsonb#>>'{draft,term}'))>0"
            )
            parameters = (state, state, state, state, query)
            count = connection.execute("SELECT count(*) " + condition, parameters).fetchone()
            assert count is not None
            rows = connection.execute(
                "SELECT d.id,r.id " + condition + " ORDER BY d.created_at,d.id OFFSET %s LIMIT %s",
                (*parameters, offset, limit),
            ).fetchall()
            items = []
            for identity, review_id in rows:
                reviewed = self._reviewed(connection, str(identity)) if review_id else None
                definition = (
                    reviewed.definition if reviewed else self._definition(connection, str(identity))
                )
                items.append(
                    DefinitionQueueItem(
                        definition=definition,
                        state="PENDING_REVIEW"
                        if reviewed is None
                        else "APPROVED"
                        if reviewed.review.decision == "APPROVE"
                        else "REJECTED",
                        review=reviewed,
                    )
                )
            return DefinitionQueue.model_validate(
                {
                    "items": tuple(items),
                    "state": state,
                    "query": query,
                    "offset": offset,
                    "limit": limit,
                    "total": count[0],
                }
            )

    def _reviewed(self, connection: DatabaseConnection, identity: str) -> ReviewedDefinition:
        definition = self._definition(connection, identity)
        row = connection.execute(
            "SELECT id,reviewer_id,review_bytes,review_sha256 "
            "FROM regintel.learning_reviews WHERE definition_id=%s",
            (UUID(identity),),
        ).fetchone()
        if row is None:
            raise LearningConflict("An explicit immutable review is required before publication.")
        return ReviewedDefinition(
            definition=definition,
            review_id=str(row[0]),
            reviewed_by=str(row[1]),
            review=LearningReview.model_validate_json(_bytes(row[2], row[3])),
        )

    def reviewed(self, identity: str, user: User) -> ReviewedDefinition:
        with self.transaction(user, admin=True) as connection:
            if (
                connection.execute(
                    "SELECT id FROM regintel.learning_reviews WHERE definition_id=%s",
                    (UUID(identity),),
                ).fetchone()
                is None
            ):
                raise LearningNotFound("This draft has no recorded learning review.")
            return self._reviewed(connection, identity)

    def review(self, identity: str, review: LearningReview, user: User) -> ReviewedDefinition:
        review = LearningReview.model_validate(review.model_dump(mode="python"))
        body = canonical_bytes(review)
        with self.transaction(user, admin=True) as connection:
            self._definition(connection, identity)
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("learning-review:" + identity,),
            )
            existing = connection.execute(
                "SELECT review_bytes,reviewer_id,review_sha256 "
                "FROM regintel.learning_reviews WHERE definition_id=%s",
                (UUID(identity),),
            ).fetchone()
            if existing is not None:
                if _bytes(existing[0], existing[2]) != body or existing[1] != user.id:
                    raise LearningConflict(
                        "A review is immutable; submit a corrected definition draft."
                    )
            else:
                connection.execute(
                    "INSERT INTO regintel.learning_reviews "
                    "(id,definition_id,review_bytes,review_sha256,reviewer_id,auth_version) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        uuid4(),
                        UUID(identity),
                        body,
                        hashlib.sha256(body).hexdigest(),
                        user.id,
                        user.auth_version,
                    ),
                )
            return self._reviewed(connection, identity)

    def publish(self, request: PublishLearning, user: User) -> GlossaryVersion:
        request = PublishLearning.model_validate(request.model_dump(mode="python"))
        with self.transaction(user, admin=True) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (0x4C4541524E494E47,))
            current = connection.execute(
                "SELECT version_id FROM regintel.learning_head WHERE singleton"
            ).fetchone()
            parent = str(current[0]) if current else None
            if request.parent_glossary_version_id != parent:
                raise LearningConflict("The glossary changed; select its current parent version.")
            result = GlossaryVersion(
                glossary_version_id=str(uuid4()),
                parent_glossary_version_id=parent,
                definitions=tuple(
                    self._reviewed(connection, identity) for identity in request.definition_ids
                ),
            )
            body = canonical_bytes(result)
            connection.execute(
                "INSERT INTO regintel.learning_versions "
                "(id,manifest,manifest_sha256,published_by,auth_version) "
                "VALUES (%s,%s,%s,%s,%s)",
                (
                    UUID(result.glossary_version_id),
                    body,
                    hashlib.sha256(body).hexdigest(),
                    user.id,
                    user.auth_version,
                ),
            )
            connection.execute(
                "INSERT INTO regintel.learning_head(singleton,version_id) VALUES (true,%s) "
                "ON CONFLICT(singleton) DO UPDATE SET version_id=EXCLUDED.version_id",
                (UUID(result.glossary_version_id),),
            )
            return result

    def overview(self, user: User) -> LearningOverview:
        with self.transaction(user) as connection:
            row = connection.execute(
                "SELECT version_id FROM regintel.learning_head WHERE singleton"
            ).fetchone()
            return LearningOverview(
                state="AVAILABLE" if row else "NO_PUBLISHED_GLOSSARY",
                glossary_version_id=str(row[0]) if row else None,
            )

    def glossary(self, identity: str, user: User) -> GlossaryVersion:
        with self.transaction(user) as connection:
            row = connection.execute(
                "SELECT manifest,manifest_sha256 FROM regintel.learning_versions WHERE id=%s",
                (UUID(identity),),
            ).fetchone()
            if row is None:
                raise LearningNotFound("The selected glossary version is unavailable.")
            body = _bytes(row[0], row[1])
            result = GlossaryVersion.model_validate_json(body)
            if result.glossary_version_id != identity or canonical_bytes(result) != body:
                raise LearningUnavailable("Learning history differs from its selected version.")
            return result
