"""Typed application configuration; credentials stay outside source control."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Environment variables are prefixed to avoid unrelated host settings."""

    model_config = SettingsConfigDict(env_prefix="REGINTEL_", extra="ignore")

    environment: Environment = "development"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
