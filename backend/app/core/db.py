"""Engine and session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def build_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Verifies a pooled connection is alive before handing it out. Without this,
        # the first query after a database failover fails rather than reconnecting.
        pool_pre_ping=True,
        echo=settings.debug,
    )


engine: AsyncEngine = build_engine()

# expire_on_commit=False: after commit, ORM objects stay usable for serialisation
# instead of triggering a lazy reload against a session whose tenant context has
# already been reset by the transaction ending.
session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)
