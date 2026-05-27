"""Shared base settings for every Astraeus service.

Each service composes a top-level ``Settings`` from these typed sub-models. The
:class:`Environment` enum gates anything that should differ between local, CI,
staging, and prod (sample rates, log formats, secret expectations).

Convention: every env var is namespaced ``ASTRAEUS_<DOMAIN>_<KEY>`` with double-
underscore (``__``) used as the nesting delimiter. Adding a new variable
requires a corresponding entry in ``.env.example``; ``scripts/env-lint.py``
fails CI on parity drift.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PROD = "prod"


def _config(prefix: str) -> SettingsConfigDict:
    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )


class AppSettings(BaseSettings):
    model_config = _config("ASTRAEUS_APP_")

    name: str = "astraeus"
    version: str = "0.1.0"
    git_sha: str | None = None
    build_time: str | None = None


class DatabaseSettings(BaseSettings):
    model_config = _config("ASTRAEUS_DB_")

    host: str = "localhost"
    port: int = 5432
    user: str = "astraeus"
    password: SecretStr = SecretStr("astraeus")
    name: str = "astraeus"
    pool_size: int = 10
    pool_max_overflow: int = 20
    pool_timeout_seconds: int = 30
    echo: bool = False

    @property
    def dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.name}"
        )

    @property
    def sync_dsn(self) -> str:
        """Sync DSN, used by Alembic which does not natively run async."""
        return (
            f"postgresql+psycopg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RedisSettings(BaseSettings):
    model_config = _config("ASTRAEUS_REDIS_")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr | None = None

    @property
    def url(self) -> str:
        auth = f":{self.password.get_secret_value()}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class KafkaSettings(BaseSettings):
    model_config = _config("ASTRAEUS_KAFKA_")

    bootstrap_servers: str = "localhost:9092"
    client_id: str = "astraeus"
    schema_registry_url: str | None = None


class ObservabilitySettings(BaseSettings):
    model_config = _config("ASTRAEUS_OBS_")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    otlp_endpoint: str = "http://localhost:4317"
    otlp_insecure: bool = True
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)


class Settings(BaseSettings):
    """Top-level settings; compose into per-service settings via inheritance."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    env: Environment = Environment.LOCAL
    app: AppSettings = Field(default_factory=AppSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
