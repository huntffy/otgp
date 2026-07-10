"""Binding a database session to exactly one tenant.

Every query the application issues runs inside a transaction that has declared which
tenant it speaks for. Postgres Row-Level Security then filters rows; the application
never adds ``WHERE tenant_id = ...`` by hand, because a filter that must be remembered
is a filter that will eventually be forgotten.

The guarantee this module provides:

    A session obtained any way other than through ``tenant_session()`` sees no
    tenant-scoped rows at all.

That holds because every policy compares ``tenant_id`` against
``current_setting('otgp.tenant_id', true)``, which is NULL when unset, and
``tenant_id = NULL`` is never true. Forgetting to set tenant context therefore
returns an empty result, not the whole table.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory

# Namespaced so it cannot collide with a Postgres GUC or another extension's setting.
TENANT_SETTING = "otgp.tenant_id"

_SET_TENANT = text(f"SELECT set_config('{TENANT_SETTING}', :tenant_id, true)")


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Yield a session scoped to ``tenant_id`` for the life of one transaction.

    ``set_config(..., is_local => true)`` ties the setting to the transaction. This is
    not a stylistic choice. With a connection pool, a session-scoped setting outlives
    the request, returns to the pool still carrying the previous tenant's identity, and
    is handed to whoever asks next. Transaction scope means COMMIT and ROLLBACK both
    clear it, and there is no path that leaves it set.

    ``set_config`` is used rather than ``SET LOCAL`` because ``SET`` is parsed before
    bind parameters are substituted, so the tenant id would have to be interpolated
    into the SQL string. Here it binds as an ordinary parameter.
    """
    async with session_factory() as session, session.begin():
        await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
        yield session


@asynccontextmanager
async def privileged_session() -> AsyncIterator[AsyncSession]:
    """A session with no tenant bound, for operations that legitimately span tenants.

    Creating a tenant, listing tenants for the admin console, and running the migration
    seeder all happen before any tenant exists to scope to.

    This does **not** disable Row-Level Security — the application role has NOBYPASSRLS
    and cannot. It simply leaves the tenant setting unset, so tenant-scoped tables return
    zero rows. Only ``tenant`` and ``permission``, which carry no policy, are readable.
    That is the intended blast radius: a bug that reaches for this helper by mistake
    reads nothing, rather than reading everything.
    """
    async with session_factory() as session, session.begin():
        yield session


async def current_tenant(session: AsyncSession) -> uuid.UUID | None:
    """Return the tenant bound to this transaction, or None. Intended for assertions."""
    result = await session.execute(text(f"SELECT current_setting('{TENANT_SETTING}', true)"))
    raw = result.scalar_one_or_none()
    return uuid.UUID(raw) if raw else None
