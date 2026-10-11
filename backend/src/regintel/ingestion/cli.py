"""Explicit replay of unsent PostgreSQL dispatch intents through existing Redis."""

import argparse
from pathlib import Path

import psycopg

from regintel.db.config import load_database_settings
from regintel.ingestion.broker import create_celery, sender
from regintel.ingestion.config import native_ingestion_settings
from regintel.ingestion.repository import JobRepository

ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay durable unsent filing jobs.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    try:
        settings = native_ingestion_settings(ROOT, args.env_file)
        repository = JobRepository(load_database_settings(args.env_file))
        count = repository.dispatch(sender(create_celery(settings)))
        print(f"Dispatch replay finished: {count} sent; failed intents remain in PostgreSQL.")
    except (OSError, ValueError, psycopg.Error):
        raise SystemExit("Dispatch configuration/storage unavailable; secrets omitted.") from None
