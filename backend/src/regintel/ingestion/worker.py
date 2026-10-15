"""Linux-only approved worker entry point. Payloads contain canonical IDs only."""

import os
import subprocess
from pathlib import Path

from pydantic import SecretStr

from regintel.db.config import DatabaseSettings
from regintel.ingestion.broker import create_celery, register_source_task
from regintel.ingestion.config import worker_ingestion_settings
from regintel.ingestion.parser import ParserProcessor
from regintel.ingestion.repository import JobRepository
from regintel.ingestion.storage import SourceStorage
from regintel.processing.broker import register_task
from regintel.processing.repository import ProcessingUnavailable

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


def _process_stages(job_id: str) -> None:
    # Fixed executable/module and validated UUID only. Separate environments keep
    # the frozen parser package inventory unchanged inside this one container.
    executable = Path("/app/backend/.stages-venv/bin/python")
    try:
        result = subprocess.run(
            [str(executable), "-m", "regintel.processing.cli", "run-worker", "--job-id", job_id],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise ProcessingUnavailable("Stage executable temporarily unavailable.") from None
    if result.returncode == 2 or result.returncode < 0:
        raise ProcessingUnavailable("Stage worker temporarily unavailable.")
    if result.returncode != 0:
        raise RuntimeError("Stage worker failed; diagnostics omitted.")


process_stages = register_task(app, _process_stages)
