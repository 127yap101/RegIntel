"""Operator-invoked database commands with explicit configuration and safe errors."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from regintel.db.checks import check_database
from regintel.db.config import load_database_settings
from regintel.db.migrations import DEFAULT_MIGRATIONS, MigrationError, migrate, migration_status


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit RegIntel PostgreSQL foundation commands")
    parser.add_argument("command", choices=("migrate", "status", "check"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS)
    parser.add_argument("--expected-postgres", default="16.15")
    parser.add_argument("--expected-vector", default="0.8.7")
    options = parser.parse_args(arguments)
    try:
        settings = load_database_settings(options.env_file)
        if options.command == "migrate":
            result = asdict(migrate(settings, options.migrations_dir))
        elif options.command == "status":
            result = asdict(migration_status(settings, options.migrations_dir))
        else:
            result = asdict(
                check_database(settings, options.expected_postgres, options.expected_vector)
            )
        print(json.dumps(result))
        return 0
    except ValidationError:
        print("Database configuration is invalid; secret values are omitted.", file=sys.stderr)
    except (OSError, ValueError):
        print("The selected database environment file is missing or invalid.", file=sys.stderr)
    except MigrationError as error:
        print(str(error), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
