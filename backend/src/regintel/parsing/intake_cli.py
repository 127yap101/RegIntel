"""Check or import explicitly selected retained native captures; never approve facts."""

import argparse
import getpass
import json
import sys
import warnings
from pathlib import Path

from regintel.auth.config import load_auth_settings
from regintel.auth.errors import InvalidAuthentication
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.db.config import load_database_settings
from regintel.ingestion.config import native_ingestion_settings
from regintel.ingestion.storage import SourceStorage
from regintel.numerical.repository import NumericalRepository
from regintel.parsing.configuration import load_runtime_configuration
from regintel.parsing.intake import import_intake, load_intake_plan, prepare_intake


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "import"))
    parser.add_argument("--plan", type=Path, required=True, help="Absolute ignored local plan.")
    parser.add_argument("--project-root", type=Path, help="Explicit installation for import.")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--auth-env-file", type=Path)
    parser.add_argument("--username", help="Existing local administrator; password is prompted.")
    args = parser.parse_args()
    if args.action == "import" and any(
        item is None
        for item in (args.project_root, args.env_file, args.auth_env_file, args.username)
    ):
        parser.error("Import requires project-root, env-file, auth-env-file and username.")
    try:
        plan = load_intake_plan(args.plan)
        if args.action == "check":
            receipt = prepare_intake(plan).check
        else:
            database = load_database_settings(args.env_file)
            auth = AuthService(
                PostgreSQLAuthRepository(database), load_auth_settings(args.auth_env_file)
            )
            # A missing terminal must fail, never fall back to an echoed password.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Existing administrator password: ")
            user = auth.current_user(auth.login(args.username, password))
            del password
            if user.role != "admin":
                raise InvalidAuthentication("A current administrator is required.")
            settings = native_ingestion_settings(args.project_root, args.env_file)
            source = NumericalRepository(
                database,
                SourceStorage(settings),
                load_runtime_configuration(Path(plan.parser_configuration.path)),
            )
            outcome = import_intake(source, plan, user)
            print(outcome.model_dump_json())
            return 0
        print(receipt.model_dump_json())
        return 0
    except Exception:
        # SDK, database and validation exceptions may retain private text/secrets/paths.
        print(
            json.dumps({"status": "INTAKE_FAILED", "acceptance_eligible": False}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
