"""Explicit private-worker execution and native dispatch of unfinished workflows."""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr

from regintel.db.config import DatabaseSettings, load_database_settings
from regintel.ingestion.broker import create_celery
from regintel.ingestion.config import native_ingestion_settings
from regintel.ingestion.repository import JobRepository
from regintel.processing.broker import sender
from regintel.processing.repository import (
    UNAVAILABLE,
    ProcessingConflict,
    ProcessingFailure,
    ProcessingRepository,
    ProcessingUnavailable,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("--env-file", type=Path, required=True)
    dispatch.add_argument("--job-id")
    dispatch.add_argument("--limit", type=int, default=100)
    run = sub.add_parser("run-worker")
    run.add_argument("--job-id", required=True)
    args = parser.parse_args()
    try:
        if args.job_id is not None:
            identifier = UUID(args.job_id)
            if str(identifier) != args.job_id or identifier.version != 4:
                raise ValueError("A canonical job ID is required.")
        if args.command == "dispatch":
            root = Path(__file__).resolve().parents[4]
            database = load_database_settings(args.env_file)
            settings = native_ingestion_settings(root, args.env_file)
            count = ProcessingRepository(database).dispatch(
                sender(create_celery(settings)), job_id=args.job_id, limit=args.limit
            )
            print(json.dumps({"dispatched": count}))
        else:
            from regintel.processing.processor import Processor

            database = DatabaseSettings(database_url=SecretStr(os.environ["REGINTEL_DATABASE_URL"]))
            factory = JobRepository(database, worker=True).connect
            repository = ProcessingRepository(database, connection_factory=factory)
            Processor(repository).run(args.job_id)
        return 0
    except (*UNAVAILABLE, ProcessingUnavailable):
        print("Processing prerequisites temporarily unavailable; secrets omitted.")
        return 2
    except (ProcessingConflict, ProcessingFailure, ValueError, KeyError, OSError):
        print("Processing invocation failed; secrets and source diagnostics omitted.")
        return 1
    except Exception:
        print("Processing invocation failed; secrets and source diagnostics omitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
