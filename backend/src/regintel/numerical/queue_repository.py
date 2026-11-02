"""Private historical numerical discovery; never a fresh gate or approval path."""

import psycopg

from regintel.auth.types import User
from regintel.db.migrations import MigrationError
from regintel.entities.models import canonical_bytes
from regintel.numerical.gate_models import MAX_GATE_RESULT_BYTES, BoundNumericalGateRun
from regintel.numerical.queue_models import (
    MAX_QUEUE_BYTES,
    NumericalGateQueueItem,
    NumericalGateQueuePage,
    NumericalGateQueueRequest,
)
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
    _checked,
)
from regintel.numerical.review_models import MAX_REVIEW_BYTES, ReviewedNumericalContext


def queue_item(row: tuple[object, ...]) -> NumericalGateQueueItem:
    (
        identity,
        context,
        parse,
        input_sha,
        result_bytes,
        result_sha,
        configuration,
        state,
        version,
        source_sha,
        company,
        document_type,
        context_version,
        context_blob,
        parse_blob,
        context_source_sha,
        review_id,
        request_bytes,
        request_sha,
        review_bytes,
        review_sha,
        review_configuration,
        reviewed_by,
        auth_version,
    ) = row
    body = _checked(result_bytes, result_sha, MAX_GATE_RESULT_BYTES)
    gate = BoundNumericalGateRun.model_validate_json(body)
    if (
        canonical_bytes(gate) != body
        or gate.id != str(identity)
        or gate.context_record_id != str(context)
        or gate.parse_version_id != str(parse)
        or gate.input_sha256 != input_sha
        or gate.configuration_sha256 != configuration
        or gate.state != state
        or gate.source_sha256 != source_sha
        or str(context_version) != str(version)
        or context_blob != parse_blob
        or context_source_sha != source_sha
    ):
        raise NumericalSourceError("Queued numerical metadata differs from its recorded result.")
    review = None
    if review_id is not None:
        original = _checked(request_bytes, request_sha, MAX_REVIEW_BYTES)
        recorded = _checked(review_bytes, review_sha, MAX_REVIEW_BYTES)
        review = ReviewedNumericalContext.model_validate_json(recorded)
        if (
            canonical_bytes(review) != recorded
            or canonical_bytes(review.request) != original
            or review.id != str(review_id)
            or review.configuration_sha256 != review_configuration
            or review.reviewed_by != str(reviewed_by)
            or review.auth_version != auth_version
        ):
            raise NumericalSourceError("Queued review metadata differs from its immutable audit.")
    elif any(
        value is not None
        for value in (
            request_bytes,
            request_sha,
            review_bytes,
            review_sha,
            review_configuration,
            reviewed_by,
            auth_version,
        )
    ):
        raise NumericalSourceError("An unreviewed gate cannot retain a partial review audit.")
    return NumericalGateQueueItem.model_validate(
        {
            "filing_version_id": str(version),
            "company_name_raw": company,
            "document_type": document_type,
            "gate": gate,
            "review": review,
        }
    )


class NumericalGateQueueRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def queue(self, selection: NumericalGateQueueRequest, user: User) -> NumericalGateQueuePage:
        selection = NumericalGateQueueRequest.model_validate(selection.model_dump(mode="python"))
        try:
            with self.source.connect() as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                _authorize(connection, user)
                rows = connection.execute(
                    "SELECT g.id,g.context_record_id,g.parse_version_id,g.input_sha256,"
                    "g.result_bytes,g.result_sha256,g.configuration_sha256,g.state,"
                    "v.id,b.sha256,f.company_name_raw,v.document_type,"
                    "c.filing_version_id,c.source_blob_id,p.source_blob_id,c.source_sha256,"
                    "r.id,r.request_bytes,r.request_sha256,r.review_bytes,r.review_sha256,"
                    "r.configuration_sha256,r.reviewed_by,r.auth_version "
                    "FROM regintel.bound_numerical_gate_runs g "
                    "JOIN regintel.parse_versions p ON p.id=g.parse_version_id "
                    "JOIN regintel.numerical_context_records c ON c.id=g.context_record_id "
                    "JOIN regintel.filing_versions v ON v.id=p.filing_version_id "
                    "JOIN regintel.source_blobs b ON b.id=v.source_blob_id "
                    "JOIN regintel.filings f ON f.id=v.filing_id "
                    "LEFT JOIN regintel.numerical_context_reviews r ON r.gate_run_id=g.id "
                    "WHERE (%s='ALL' OR g.state=%s) "
                    "AND (%s='ALL' OR (%s='UNREVIEWED' AND r.id IS NULL) OR "
                    "convert_from(r.review_bytes,'UTF8')::jsonb#>>'{request,decision}'=%s) "
                    "AND position(lower(%s) in lower(f.company_name_raw))>0 "
                    "ORDER BY g.id OFFSET %s LIMIT %s",
                    (
                        selection.state,
                        selection.state,
                        selection.review,
                        selection.review,
                        selection.review,
                        selection.query,
                        selection.offset,
                        selection.limit + 1,
                    ),
                ).fetchall()
                size = sum(
                    len(value)
                    for row in rows
                    for value in row
                    if isinstance(value, (bytes, memoryview))
                )
                if size > MAX_QUEUE_BYTES:
                    raise NumericalUnavailable("The stored queue exceeds its payload budget.")
                # Validate the lookahead as well: corrupt continuation data is not success.
                items = tuple(queue_item(row) for row in rows)
                return NumericalGateQueuePage(
                    scope="RETAINED_HISTORY_ONLY",
                    state_filter=selection.state,
                    review_filter=selection.review,
                    query=selection.query,
                    offset=selection.offset,
                    limit=selection.limit,
                    has_more=len(items) > selection.limit,
                    items=items[: selection.limit],
                )
        except (NumericalAuthorizationError, NumericalSourceError, NumericalUnavailable):
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable("Numerical queue storage is unavailable.") from None
        except (psycopg.Error, ValueError, OSError):
            raise NumericalSourceError(
                "The retained numerical queue could not be verified."
            ) from None
