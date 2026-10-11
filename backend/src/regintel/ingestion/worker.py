"""Linux-only approved worker entry point. Payloads contain canonical IDs only."""

import os
from pathlib import Path

from pydantic import SecretStr

from regintel.db.config import DatabaseSettings
from regintel.ingestion.broker import create_celery, register_source_task
from regintel.ingestion.config import worker_ingestion_settings
from regintel.ingestion.parser import ParserProcessor
from regintel.ingestion.repository import JobRepository
from regintel.ingestion.storage import SourceStorage

settings = worker_ingestion_settings()
database = DatabaseSettings(database_url=SecretStr(os.environ["REGINTEL_DATABASE_URL"]))
repository = JobRepository(database, worker=True)
storage = SourceStorage(settings, create=False)
app = create_celery(settings)
if settings.parser_configuration is None:
    raise ValueError("The approved worker requires an explicitly selected parser descriptor.")
processor = ParserProcessor(
    storage, settings.parser_configuration, Path(os.environ["REGINTEL_MODEL_ROOT"])
)


def _process(job_id: str) -> None:
    if settings.parser_configuration is None:
        raise ValueError("The selected parser descriptor is unavailable.")
    repository.parse_job(job_id, settings.parser_configuration, processor)


verify_source = register_source_task(app, _process)
