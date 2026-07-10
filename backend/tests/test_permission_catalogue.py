"""The permission catalogue in code and the one in the database must not drift.

``require()`` rejects any code absent from ``ALL_PERMISSIONS``, and roles can only grant
codes present in the ``permission`` table. If the two disagree, a permission becomes
either ungrantable or uncheckable — and both failures are silent.
"""

from __future__ import annotations

import psycopg

from app.core.permissions import ALL_PERMISSIONS


def test_database_catalogue_matches_the_code_catalogue(app_conn: psycopg.Connection) -> None:
    seeded = {row[0] for row in app_conn.execute("SELECT code FROM permission").fetchall()}
    assert seeded == set(ALL_PERMISSIONS), (
        f"only in database: {sorted(seeded - ALL_PERMISSIONS)}; "
        f"only in code: {sorted(ALL_PERMISSIONS - seeded)}"
    )


def test_permission_table_is_readable_without_tenant_context(
    app_conn: psycopg.Connection,
) -> None:
    """The catalogue is global and carries no RLS policy, unlike every tenant table.

    A permission code is a property of the software, not of a customer, so there is
    nothing here to isolate — and the login path must read it before a tenant is known.
    """
    assert app_conn.execute("SELECT count(*) FROM permission").fetchone()[0] == len(ALL_PERMISSIONS)


def test_every_permission_code_follows_resource_action_form() -> None:
    for code in ALL_PERMISSIONS:
        resource, _, action = code.partition(":")
        assert resource and action, f"{code!r} is not '<resource>:<action>'"
        assert code.islower(), f"{code!r} must be lowercase"
