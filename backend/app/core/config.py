"""Application settings, loaded from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Every field is required unless it has a safe default. There is no fallback
    connection string: a missing ``OTGP_DATABASE_URL`` must stop the process at import
    rather than silently connect to a developer's local database in production.
    """

    model_config = SettingsConfigDict(
        env_prefix="OTGP_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "ci", "staging", "production"] = "local"
    debug: bool = False

    # Connection used to serve requests. Points at the unprivileged role, which is the
    # only role for which Row-Level Security is enforced.
    database_url: PostgresDsn

    # Connection used by Alembic. Points at the schema owner, which may run DDL.
    # Distinct from database_url on purpose; see docs/ARCHITECTURE.md.
    migration_database_url: PostgresDsn

    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")

    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "otgp"

    # Connections held open per worker process. PgBouncer sits in front in production,
    # so this stays small; each Postgres backend costs ~10 MB of server RAM.
    db_pool_size: int = 5
    db_max_overflow: int = 10

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Settings are immutable for the lifetime of the process."""
    return Settings()  # type: ignore[call-arg]  # values arrive from the environment
