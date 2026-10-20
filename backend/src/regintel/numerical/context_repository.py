"""Read-only administrator inspection of uploaded numerical preparation snapshots."""

import psycopg

from regintel.auth.types import User
from regintel.candidates.repository import CandidateNotFound, load_metrics
from regintel.db.migrations import MigrationError
from regintel.entities.repository import _snapshot
from regintel.ingestion.storage import UploadError
from regintel.numerical.context_gate import inspect_context
from regintel.numerical.context_models import (
    NumericalContextDraft,
    NumericalContextInput,
    NumericalContextInspection,
)
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
    _blob,
    _checked,
    _stored,
)
from regintel.numerical.source_pages import preparation_code_sha256
from regintel.validation.models import NumericMetricPolicy


class NumericalContextRepository:
    """No review/acceptance write path and no caller/model-supplied registry or policy."""

    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def inspect(self, draft: NumericalContextDraft, user: User) -> NumericalContextInspection:
        draft = NumericalContextDraft.model_validate(draft.model_dump(mode="python"))
        try:
            with self.source.connect() as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                _authorize(connection, user)
                pages = tuple(_stored(connection, identity) for identity in draft.capture_ids)
                blob = _blob(connection, draft.filing_version_id)
                self.source.storage.verify(blob)
                registry = _snapshot(connection)
                try:
                    metric = load_metrics(connection, (draft.metric_id,))[0]
                except CandidateNotFound:
                    metric = None
                row = connection.execute(
                    "SELECT policy_bytes,policy_sha256 FROM regintel.numeric_metric_policies "
                    "WHERE metric_id=%s",
                    (draft.metric_id,),
                ).fetchone()
                policy = (
                    NumericMetricPolicy.model_validate_json(_checked(row[0], row[1], 64_000))
                    if row is not None
                    else None
                )
                return inspect_context(
                    NumericalContextInput(
                        draft=draft,
                        pages=pages,
                        registry=registry,
                        metric=metric,
                        policy=policy,
                        sdk_configuration_sha256=self.source.configuration.sdk_configuration_sha256,
                        preparation_code_sha256=preparation_code_sha256(),
                    )
                )
        except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable("Numerical context inspection is unavailable.") from None
        except (psycopg.Error, OSError, ValueError, UploadError):
            raise NumericalSourceError(
                "Numerical context source or approval snapshot is invalid."
            ) from None
