"""Test fixtures.

These tests run against a real PostGIS database. Row-Level Security, GiST indexes and
trigger behaviour cannot be exercised against SQLite or a mock, and those are precisely
the parts of this schema most worth testing.

    docker compose up -d postgres
    cd backend && alembic upgrade head && pytest
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest


def _dsn(env_var: str) -> str:
    """Read a SQLAlchemy URL from the environment and strip the driver for psycopg."""
    url = os.environ.get(env_var)
    if not url:
        pytest.skip(f"{env_var} is not set; start the database and export it from .env")
    return url.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(scope="session")
def owner_dsn() -> str:
    """Schema owner. Runs migrations and seeds fixtures. Subject to FORCEd RLS."""
    return _dsn("OTGP_MIGRATION_DATABASE_URL")


@pytest.fixture(scope="session")
def app_dsn() -> str:
    """The unprivileged role the application uses. The only role RLS protects."""
    return _dsn("OTGP_DATABASE_URL")


@pytest.fixture
def app_conn(app_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(app_dsn) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def two_tenants(owner_dsn: str) -> Iterator[dict[str, uuid.UUID]]:
    """Two fully-populated tenants, so every isolation test has something to leak.

    A test that asserts "tenant A sees no rows" proves nothing unless tenant B's rows
    exist and are otherwise visible.

    Cleanup happens on *setup*, not teardown. TRUNCATE needs ACCESS EXCLUSIVE, and any
    concurrently open read transaction — such as the ``app_conn`` fixture, which pytest
    tears down *after* this one — holds ACCESS SHARE and would block it indefinitely.
    Truncating up front makes each test independent without ever contending for a lock.
    """
    with psycopg.connect(owner_dsn, autocommit=True) as conn:
        # Turn any unexpected lock contention into an immediate, readable failure
        # rather than a CI job that hangs until the runner times out.
        conn.execute("SET lock_timeout = '5s'")
        conn.execute("TRUNCATE tenant CASCADE")
        tenants: dict[str, uuid.UUID] = {}

        for slug in ("alpha", "bravo"):
            tenant_id = conn.execute(
                "INSERT INTO tenant (slug, name) VALUES (%s, %s) RETURNING id",
                (slug, slug.title()),
            ).fetchone()[0]
            tenants[slug] = tenant_id

            # The owner is subject to FORCE ROW LEVEL SECURITY too, so seeding requires
            # a tenant context exactly like the application needs one.
            conn.execute("SELECT set_config('otgp.tenant_id', %s, false)", (str(tenant_id),))

            user_id = conn.execute(
                "INSERT INTO user_account (tenant_id, email) VALUES (%s, %s) RETURNING id",
                (tenant_id, f"engineer@{slug}.example"),
            ).fetchone()[0]
            project_id = conn.execute(
                """INSERT INTO project (tenant_id, name, slug, owner_id)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (tenant_id, f"{slug} network", f"{slug}-network", user_id),
            ).fetchone()[0]
            asset_id = conn.execute(
                """INSERT INTO asset (tenant_id, project_id, asset_type, name, code, location)
                   VALUES (%s, %s, 'tower', %s, %s, ST_SetSRID(ST_MakePoint(69.2, 34.5), 4326))
                   RETURNING id""",
                (tenant_id, project_id, f"{slug} tower", f"TWR-{slug.upper()}-1"),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO tower (id, height_m, structure_type) VALUES (%s, 45, 'lattice')",
                (asset_id,),
            )
            conn.execute(
                """INSERT INTO audit_log (tenant_id, action, entity_type, entity_id)
                   VALUES (%s, 'asset.create', 'asset', %s)""",
                (tenant_id, asset_id),
            )

        conn.execute("SELECT set_config('otgp.tenant_id', '', false)")

    yield tenants


def set_tenant(conn: psycopg.Connection, tenant_id: uuid.UUID) -> None:
    """Bind the current transaction to a tenant, exactly as app.core.tenancy does."""
    conn.execute("SELECT set_config('otgp.tenant_id', %s, true)", (str(tenant_id),))
