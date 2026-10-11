"""Actual Celery registration/eager retry behavior; no fake task implementation."""

from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import psycopg
import pytest
from pydantic import SecretStr

from regintel.ingestion.broker import create_celery, register_source_task
from regintel.ingestion.config import IngestionSettings


class EagerResult(Protocol):
    state: str
    result: object


class EagerTask(Protocol):
    max_retries: int | None

    def apply(self, args: tuple[object, ...], *, throw: bool) -> EagerResult: ...


@pytest.mark.parametrize("failure", [psycopg.OperationalError, psycopg.InterfaceError])
def test_actual_celery_transient_storage_failure_retries_to_success(
    tmp_path: Path, failure: type[Exception]
) -> None:
    settings = IngestionSettings(
        source_root=tmp_path, broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0")
    )
    app = create_celery(settings)
    attempts: list[str] = []

    def process(job_id: str) -> None:
        attempts.append(job_id)
        if len(attempts) <= 5:
            raise failure("Synthetic private connection diagnostic")

    task = cast(EagerTask, register_source_task(app, process))
    assert task.max_retries is None
    identifier = str(uuid4())
    result = task.apply((identifier,), throw=False)
    assert result.state == "SUCCESS" and result.result is None
    assert attempts == [identifier] * 6


def test_untrusted_queue_ids_never_reach_storage(tmp_path: Path) -> None:
    settings = IngestionSettings(
        source_root=tmp_path, broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0")
    )
    seen: list[str] = []
    task = cast(EagerTask, register_source_task(create_celery(settings), seen.append))
    for identifier in (None, 0, "bad", str(uuid4()).upper(), "0" * 36):
        assert task.apply((identifier,), throw=False).state == "SUCCESS"
    assert seen == []
