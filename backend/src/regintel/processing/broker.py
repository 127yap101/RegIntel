"""ID-only delivery on the existing Celery application and private queue."""

from collections.abc import Callable
from uuid import UUID

import psycopg

from regintel.ingestion.broker import CeleryApplication, WorkerStorageUnavailable
from regintel.processing.repository import ProcessingUnavailable

TASK_NAME = "regintel.processing.run"


def sender(application: CeleryApplication) -> Callable[[str], None]:
    def send(job_id: str) -> None:
        identifier = UUID(job_id)
        if str(identifier) != job_id or identifier.version != 4:
            raise ValueError("Dispatch requires a canonical job ID.")
        application.send_task(
            TASK_NAME, args=[job_id], task_id=job_id, retry=False, ignore_result=True
        )

    return send


def register_task(application: CeleryApplication, process: Callable[[str], None]) -> object:
    def run(job_id: str) -> None:
        if not isinstance(job_id, str):
            return
        try:
            identifier = UUID(job_id)
        except ValueError:
            return
        if str(identifier) != job_id or identifier.version != 4:
            return
        try:
            process(job_id)
        except (ProcessingUnavailable, psycopg.OperationalError, psycopg.InterfaceError):
            raise WorkerStorageUnavailable("Processing storage temporarily unavailable.") from None

    return application.task(
        name=TASK_NAME,
        autoretry_for=(WorkerStorageUnavailable,),
        retry_backoff=True,
        retry_backoff_max=60,
        retry_kwargs={"max_retries": None},
        shared=False,
        max_retries=None,
    )(run)
