"""Narrow typed boundary around Celery's untyped library API."""

from collections.abc import Callable
from importlib import import_module
from typing import Protocol, cast
from uuid import UUID

import psycopg

from regintel.ingestion.config import IngestionSettings

TASK_NAME = "regintel.ingestion.verify_source"


class WorkerStorageUnavailable(Exception):
    """Sanitized retriable infrastructure error, without a connection diagnostic."""


class CeleryConfiguration(Protocol):
    def update(self, **settings: object) -> None: ...


class CeleryApplication(Protocol):
    conf: CeleryConfiguration

    def send_task(
        self, name: str, *, args: list[str], task_id: str, retry: bool, ignore_result: bool
    ) -> object: ...

    def task(
        self,
        *,
        name: str,
        autoretry_for: tuple[type[Exception], ...],
        retry_backoff: bool,
        retry_backoff_max: int,
        retry_kwargs: dict[str, object],
        shared: bool,
        max_retries: int | None,
    ) -> Callable[[Callable[[str], None]], object]: ...


class CeleryFactory(Protocol):
    def __call__(self, name: str, *, broker: str) -> CeleryApplication: ...


def create_celery(settings: IngestionSettings) -> CeleryApplication:
    factory = cast(CeleryFactory, import_module("celery").Celery)
    application = factory("regintel-ingestion", broker=settings.broker_url.get_secret_value())
    application.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_default_queue="regintel-ingestion",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        broker_connection_timeout=3,
        broker_transport_options={
            "socket_connect_timeout": 3,
            "socket_timeout": 3,
            "visibility_timeout": 3600,
        },
        worker_hijack_root_logger=False,
        worker_redirect_stdouts=False,
    )
    return application


def sender(application: CeleryApplication) -> Callable[[str], None]:
    def send(job_id: str) -> None:
        identifier = UUID(job_id)
        if identifier.version != 4 or str(identifier) != job_id:
            raise ValueError("Only a canonical job identifier is dispatched.")
        application.send_task(
            TASK_NAME, args=[job_id], task_id=job_id, retry=False, ignore_result=True
        )

    return send


def register_source_task(application: CeleryApplication, process: Callable[[str], None]) -> object:
    def run(job_id: str) -> None:
        if not isinstance(job_id, str):
            return
        try:
            identifier = UUID(job_id)
        except ValueError:
            return
        if identifier.version != 4 or str(identifier) != job_id:
            return
        try:
            process(job_id)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            raise WorkerStorageUnavailable("Job storage temporarily unavailable.") from None

    # Infrastructure failures retry indefinitely with a bounded backoff. Source
    # validation failures commit explicit terminal outcomes instead.
    return application.task(
        name=TASK_NAME,
        autoretry_for=(WorkerStorageUnavailable,),
        retry_backoff=True,
        retry_backoff_max=60,
        retry_kwargs={"max_retries": None},
        shared=False,
        max_retries=None,
    )(run)
