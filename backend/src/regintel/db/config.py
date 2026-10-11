"""Database secrets are loaded only by an explicitly invoked database command."""

from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr

    @field_validator("database_url")
    @classmethod
    def require_postgresql_uri(cls, value: SecretStr) -> SecretStr:
        try:
            parsed = urlsplit(value.get_secret_value())
            parameters = conninfo_to_dict(value.get_secret_value())
            port = parameters.get("port")
            password = parameters.get("password")
            user = parameters.get("user")
            database = parameters.get("dbname")
            valid = (
                parsed.scheme in {"postgres", "postgresql"}
                and parsed.hostname is not None
                and parsed.username is not None
                and len(parsed.path) > 1
                and parsed.port is not None
                and isinstance(port, str)
                and port.isdecimal()
                and 1 <= int(port) <= 65535
                and isinstance(password, str)
                and bool(password)
                and isinstance(user, str)
                and bool(user)
                and isinstance(database, str)
                and bool(database)
                and not parsed.fragment
                and not parameters.keys()
                - {"host", "hostaddr", "port", "dbname", "user", "password"}
            )
        except (ValueError, psycopg.Error):
            valid = False
        if not valid:
            raise ValueError(
                "A complete PostgreSQL URI with explicit host, port, user, password and database "
                "is required; service/password-file and implicit configuration are unsupported."
            )
        return value


def load_database_settings(env_file: Path) -> DatabaseSettings:
    """Read the caller-selected project env file without changing process settings."""
    if not env_file.is_file():
        raise ValueError("The explicitly selected database environment file is missing.")
    values = dotenv_values(env_file, encoding="utf-8", interpolate=False)
    database_url = values.get("REGINTEL_DATABASE_URL")
    if not isinstance(database_url, str):
        raise ValueError("The selected environment file must contain REGINTEL_DATABASE_URL.")
    return DatabaseSettings(database_url=SecretStr(database_url))


def require_disposable_database(settings: DatabaseSettings) -> None:
    """Validate libpq's effective target before destructive integration-test cleanup."""
    parameters = conninfo_to_dict(settings.database_url.get_secret_value())
    # libpq query parameters can override the URI host/database, so inspect its
    # parsed effective values rather than trusting only the displayed URL path.
    host = parameters.get("host")
    host_address = parameters.get("hostaddr")
    database = parameters.get("dbname", "")
    if (
        host not in {"127.0.0.1", "localhost", "::1"}
        or host_address not in {None, "127.0.0.1", "::1"}
        or not isinstance(database, str)
        or not database.startswith("regintel_test_")
    ):
        raise ValueError("Integration requires a loopback, disposable regintel_test_ database.")
