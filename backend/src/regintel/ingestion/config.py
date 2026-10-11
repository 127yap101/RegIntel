"""Explicit phase-bounded ingestion configuration; no implicit credential loading."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from regintel.parsing.configuration import (
    ParserRuntimeConfiguration,
    current_runtime_code_hashes,
    load_runtime_configuration,
)


class IngestionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    source_root: Path
    broker_url: SecretStr
    max_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    max_pages: int = Field(default=2000, ge=1, le=2000)
    parser_configuration: ParserRuntimeConfiguration | None = None

    @model_validator(mode="after")
    def matching_parser_limits(self) -> "IngestionSettings":
        selected = self.parser_configuration
        if selected is not None:
            if (self.max_bytes, self.max_pages) != (
                selected.source_limits.max_file_bytes,
                selected.source_limits.max_pages,
            ):
                raise ValueError("Upload limits must match the selected parser descriptor.")
            if any(
                getattr(selected, name) != value
                for name, value in current_runtime_code_hashes().model_dump().items()
            ):
                raise ValueError("Installed parser code differs from the selected descriptor.")
        return self

    @field_validator("source_root")
    @classmethod
    def absolute_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Source storage needs an explicit absolute root.")
        return value

    @field_validator("broker_url")
    @classmethod
    def local_broker(cls, value: SecretStr) -> SecretStr:
        try:
            uri = urlsplit(value.get_secret_value())
            valid = (
                uri.scheme == "redis"
                and uri.hostname in {"127.0.0.1", "localhost", "::1", "redis"}
                and uri.port == 6379
                and uri.username in {None, ""}
                and bool(uri.password)
                and uri.path == "/0"
                and not uri.query
                and not uri.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Only the explicitly authenticated project Redis database is allowed.")
        return value

    @property
    def configuration_sha256(self) -> str:
        if self.parser_configuration is not None:
            return self.parser_configuration.processing_configuration_sha256
        # Filesystem paths and credentials do not change processing identity.
        value = {
            "stage": "source-verification-v1",
            "pypdf": "6.19.0",
            "max_bytes": self.max_bytes,
            "max_pages": self.max_pages,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def native_ingestion_settings(root: Path, env_file: Path) -> IngestionSettings:
    values = dotenv_values(env_file, interpolate=False)
    password = values.get("REDIS_PASSWORD")
    if not isinstance(password, str) or not password or not password.isalnum():
        raise ValueError("The generated project Redis secret is unavailable.")
    return IngestionSettings(
        source_root=root / "data" / "uploads",
        broker_url=SecretStr(f"redis://:{password}@127.0.0.1:6379/0"),
        parser_configuration=load_runtime_configuration(
            root / "data" / "parser-runtime-config.json"
        ),
    )


def worker_ingestion_settings() -> IngestionSettings:
    return IngestionSettings(
        source_root=Path(os.environ["REGINTEL_SOURCE_ROOT"]),
        broker_url=SecretStr(os.environ["REGINTEL_BROKER_URL"]),
        parser_configuration=load_runtime_configuration(Path(os.environ["REGINTEL_PARSER_CONFIG"])),
    )
