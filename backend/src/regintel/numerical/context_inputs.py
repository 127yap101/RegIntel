"""Load exact current preparation/approval snapshots within the caller's transaction."""

from regintel.candidates.repository import CandidateNotFound, load_metrics
from regintel.db.migrations import DatabaseConnection
from regintel.entities.repository import _snapshot
from regintel.ingestion.models import SourceBlob
from regintel.numerical.context_models import NumericalContextDraft, NumericalContextInput
from regintel.numerical.repository import NumericalRepository, _blob, _checked, _stored
from regintel.numerical.source_pages import preparation_code_sha256
from regintel.validation.models import NumericMetricPolicy


def load_context_input(
    connection: DatabaseConnection, repository: NumericalRepository, draft: NumericalContextDraft
) -> tuple[NumericalContextInput, SourceBlob]:
    pages = tuple(_stored(connection, identity) for identity in draft.capture_ids)
    primary = _blob(connection, draft.filing_version_id)
    sources = {primary.id: primary}
    for page in pages:
        blob = _blob(connection, page.filing_version_id)
        sources[blob.id] = blob
    for blob in sources.values():
        repository.storage.verify(blob)
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
        NumericMetricPolicy.model_validate_json(_checked(row[0], row[1], 65_536))
        if row is not None
        else None
    )
    return NumericalContextInput(
        draft=draft,
        pages=pages,
        registry=registry,
        metric=metric,
        policy=policy,
        sdk_configuration_sha256=repository.configuration.sdk_configuration_sha256,
        preparation_code_sha256=preparation_code_sha256(),
    ), primary
