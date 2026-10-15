"""Actual Celery processing tasks validate IDs and retry beyond the default limit."""

from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from pydantic import SecretStr

from backend.tests.test_ingestion_broker import EagerTask
from regintel.ingestion.broker import create_celery
from regintel.ingestion.config import IngestionSettings
from regintel.processing.broker import register_task
from regintel.processing.repository import ProcessingUnavailable


@pytest.mark.parametrize(
    "failure", (ProcessingUnavailable, psycopg.OperationalError, psycopg.InterfaceError)
)
def test_actual_celery_processing_retries_to_success(tmp_path: Path, failure):
    app = create_celery(
        IngestionSettings(
            source_root=tmp_path, broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0")
        )
    )
    seen = []

    def process(job_id):
        seen.append(job_id)
        if len(seen) < 6:
            raise failure("private temporary diagnostic")

    task = cast(EagerTask, register_task(app, process))
    identifier = str(uuid4())
    assert task.max_retries is None
    result = task.apply((identifier,), throw=False)
    assert result.state == "SUCCESS" and result.result is None
    assert seen == [identifier] * 6


def test_actual_task_discards_untrusted_queue_payloads(tmp_path: Path):
    app = create_celery(
        IngestionSettings(
            source_root=tmp_path, broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0")
        )
    )
    seen = []
    task = cast(EagerTask, register_task(app, seen.append))
    for value in (None, 0, "bad", str(uuid4()).upper(), {"job_id": str(uuid4())}):
        assert task.apply((value,), throw=False).state == "SUCCESS"
    assert seen == []
