"""Fixed bounded read queries; immutable domain repositories verify review payloads."""

from uuid import UUID

from regintel.admin.models import (
    MetricPage,
    QueueItem,
    QueueKind,
    QueuePage,
    ReviewFilter,
    ReviewItem,
    ReviewPage,
)
from regintel.auth.types import User
from regintel.candidates.models import MetricDefinition
from regintel.candidates.records import drafts
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, connect_database
from regintel.validation.gate import current_configuration
from regintel.validation.models import ReviewDecision, ValidationInput
from regintel.validation.repository import (
    ValidationAuthorizationError,
    ValidationConflict,
    ValidationNotFound,
    ValidationRepository,
    checked,
)

QUERIES: dict[QueueKind, str] = {
    "filings": "SELECT j.id,f.company_name_raw,j.state,j.parse_version_id,j.filing_version_id "
    "FROM regintel.filing_jobs j JOIN regintel.filing_versions v ON v.id=j.filing_version_id "
    "JOIN regintel.filings f ON f.id=v.filing_id ORDER BY j.id LIMIT %s OFFSET %s",
    "processing": "SELECT id,'Processing workflow',state,parse_version_id,NULL "
    "FROM regintel.processing_jobs ORDER BY id LIMIT %s OFFSET %s",
    "validations": "SELECT id,'Validation audit','AUDIT',parse_version_id,candidate_run_id "
    "FROM regintel.validation_runs ORDER BY id LIMIT %s OFFSET %s",
    "publications": "SELECT b.id,'Corpus build',v.state,NULL,v.parent_corpus_version_id "
    "FROM regintel.publication_builds b JOIN regintel.corpus_versions v ON v.id=b.id "
    "ORDER BY b.id LIMIT %s OFFSET %s",
}


def current_admin(connection: DatabaseConnection, user: User) -> None:
    row = connection.execute(
        "SELECT role,is_active,auth_version FROM regintel.users WHERE id=%s", (user.id,)
    ).fetchone()
    if row != ("admin", True, user.auth_version):
        raise ValidationAuthorizationError("A current administrator is required.")


def bounded(offset: int, limit: int) -> None:
    if (
        type(offset) is not int
        or type(limit) is not int
        or not 0 <= offset <= 10000
        or not 1 <= limit <= 25
    ):
        raise ValueError("Workspace pagination exceeds its bound.")


class AdminRepository:
    def __init__(self, database: DatabaseSettings) -> None:
        self.database = database
        self.validator = ValidationRepository(database)

    @staticmethod
    def start(connection: DatabaseConnection, user: User) -> None:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("SET LOCAL statement_timeout='15s'")
        current_admin(connection, user)

    def queue(self, kind: QueueKind, offset: int, limit: int, user: User) -> QueuePage:
        bounded(offset, limit)
        with connect_database(self.database) as connection, connection.transaction():
            self.start(connection, user)
            rows = connection.execute(QUERIES[kind], (limit + 1, offset)).fetchall()
            head = connection.execute(
                "SELECT corpus_version_id FROM regintel.publication_head"
            ).fetchone()
        return QueuePage(
            kind=kind,
            items=tuple(
                QueueItem.model_validate(
                    dict(
                        id=str(row[0]),
                        label=row[1],
                        state=row[2],
                        parse_version_id=str(row[3]) if row[3] is not None else None,
                        related_id=str(row[4]) if row[4] is not None else None,
                    )
                )
                for row in rows[:limit]
            ),
            offset=offset,
            limit=limit,
            has_more=len(rows) > limit,
            published_corpus_id=str(head[0]) if head is not None else None,
        )

    def review_page(
        self, run_id: str, state: ReviewFilter, offset: int, limit: int, user: User
    ) -> ReviewPage:
        bounded(offset, limit)
        with connect_database(self.database) as connection, connection.transaction():
            self.start(connection, user)
            run = self.validator._get_run(connection, run_id)
            row = connection.execute(
                "SELECT input_bytes,input_sha256 FROM regintel.validation_runs WHERE id=%s",
                (UUID(run_id),),
            ).fetchone()
            if row is None:
                raise ValidationNotFound()
            source = ValidationInput.model_validate_json(checked(row[0], row[1]))
            if source.candidate_run.id != run.candidate_run_id or source.sha256 != run.input_sha256:
                raise ValidationConflict("Review source identity differs.")
            candidate_ids = [UUID(item.id) for item in source.candidate_run.candidates]
            rows = connection.execute(
                "SELECT review_bytes,review_sha256 FROM regintel.validation_reviews "
                "WHERE candidate_id=ANY(%s) ORDER BY candidate_id",
                (candidate_ids,),
            ).fetchall()
            reviews = {
                item.candidate_id: item
                for item in (
                    ReviewDecision.model_validate_json(checked(row[0], row[1])) for row in rows
                )
            }
            current = (
                run.configuration == current_configuration()
                and self.validator._input(connection, run.candidate_run_id).sha256
                == run.input_sha256
            )
            metrics = {item.id: item.label for item in source.source.metrics}
            accepted_rows = connection.execute(
                "SELECT candidate_id,id FROM regintel.fact_observations WHERE candidate_id=ANY(%s) "
                "UNION ALL SELECT candidate_id,id FROM regintel.relation_observations "
                "WHERE candidate_id=ANY(%s)",
                (candidate_ids, candidate_ids),
            ).fetchall()
            accepted = {str(row[0]): str(row[1]) for row in accepted_rows}
            if len(accepted) != len(accepted_rows):
                raise ValidationConflict("Accepted candidate identity is ambiguous.")
            results = {item.candidate_id: item for item in run.results}
            items = tuple(
                ReviewItem(
                    candidate=record,
                    draft=draft,
                    result=results[record.id],
                    review=reviews.get(record.id),
                    metric_label=metrics.get(record.metric_id or ""),
                    accepted_observation_id=accepted.get(record.id),
                )
                for record, draft in zip(
                    source.candidate_run.candidates,
                    drafts(source.candidate_run.bundle),
                    strict=True,
                )
                if state == "ALL" or results[record.id].state == state
            )
            return ReviewPage(
                run_id=run.id,
                candidate_run_id=run.candidate_run_id,
                parse_version_id=run.parse_version_id,
                configuration_sha256=run.configuration.sha256,
                approval_current=current,
                state_filter=state,
                items=items[offset : offset + limit],
                offset=offset,
                limit=limit,
                has_more=len(items) > offset + limit,
            )

    def metrics(self, user: User) -> MetricPage:
        with connect_database(self.database) as connection, connection.transaction():
            self.start(connection, user)
            rows = connection.execute(
                "SELECT definition_bytes,definition_sha256 "
                "FROM regintel.metric_definitions ORDER BY id LIMIT 101"
            ).fetchall()
            if len(rows) > 100:
                raise ValueError("The controlled metric catalog exceeds its bound.")
            return MetricPage(
                items=tuple(
                    MetricDefinition.model_validate_json(checked(row[0], row[1])) for row in rows
                )
            )
