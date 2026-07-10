"""Adversarial tests for multi-tenant isolation.

Every test here tries to *break* isolation rather than confirm it works. The two bugs
these tests were written in response to — an unprotected joined-inheritance subtype
table, and an audit log whose UPDATE silently affected zero rows instead of raising —
both passed a "does the happy path work" review.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.conftest import set_tenant


class TestFailClosed:
    """A session that never declared a tenant must see nothing, not everything."""

    @pytest.mark.parametrize("table", ["asset", "project", "user_account", "audit_log", "tower"])
    def test_no_tenant_context_yields_no_rows(
        self, app_conn: psycopg.Connection, two_tenants: dict[str, uuid.UUID], table: str
    ) -> None:
        # `current_setting('otgp.tenant_id', true)` is NULL when unset, and
        # `tenant_id = NULL` is never true, so a forgotten context reads zero rows.
        count = app_conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        assert count == 0, f"{table} leaked {count} rows with no tenant context"

    def test_tower_subtype_is_protected_independently(
        self, app_conn: psycopg.Connection, two_tenants: dict[str, uuid.UUID]
    ) -> None:
        """Joined-table inheritance splits one entity across two tables.

        Postgres does not know they are related, so a policy on `asset` does nothing
        for `tower`. Without its own policy, `SELECT * FROM tower` would expose every
        tenant's structure heights and load ratings.
        """
        set_tenant(app_conn, two_tenants["alpha"])
        assert app_conn.execute("SELECT count(*) FROM tower").fetchone()[0] == 1


class TestReadIsolation:
    def test_tenant_sees_only_its_own_assets(
        self, app_conn: psycopg.Connection, two_tenants: dict[str, uuid.UUID]
    ) -> None:
        set_tenant(app_conn, two_tenants["alpha"])
        codes = [row[0] for row in app_conn.execute("SELECT code FROM asset").fetchall()]
        assert codes == ["TWR-ALPHA-1"]

    def test_explicit_cross_tenant_predicate_still_returns_nothing(
        self, app_conn: psycopg.Connection, two_tenants: dict[str, uuid.UUID]
    ) -> None:
        """A hostile WHERE clause cannot widen what the policy permits.

        The policy is ANDed with the query's own predicate, so naming another tenant's
        id narrows the result to the empty set rather than escaping the policy.
        """
        set_tenant(app_conn, two_tenants["alpha"])
        count = app_conn.execute(
            "SELECT count(*) FROM asset WHERE tenant_id = %s", (two_tenants["bravo"],)
        ).fetchone()[0]
        assert count == 0


class TestWriteIsolation:
    def test_cannot_insert_a_row_belonging_to_another_tenant(
        self, app_conn: psycopg.Connection, two_tenants: dict[str, uuid.UUID]
    ) -> None:
        """WITH CHECK, not just USING: without it, a tenant could write rows it then
        could not read — poisoning another tenant's data while appearing to fail."""
        set_tenant(app_conn, two_tenants["alpha"])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute(
                "INSERT INTO project (tenant_id, name, slug, owner_id) VALUES (%s,'x','x',%s)",
                (two_tenants["bravo"], uuid.UUID(int=0)),
            )


class TestAuditLogIsAppendOnly:
    """Enforced by REVOKE, not by the absence of a policy.

    An UPDATE with no matching RLS policy does not raise: it matches zero rows and
    commits. Only a privilege revocation turns tampering into an error a monitor can see.
    """

    @pytest.mark.parametrize(
        "statement",
        [
            "UPDATE audit_log SET action = 'tampered'",
            "DELETE FROM audit_log",
            "TRUNCATE audit_log",
        ],
    )
    def test_mutating_history_raises(
        self, app_conn: psycopg.Connection, two_tenants: dict[str, uuid.UUID], statement: str
    ) -> None:
        set_tenant(app_conn, two_tenants["alpha"])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute(statement)

    def test_appending_is_permitted(
        self, app_conn: psycopg.Connection, two_tenants: dict[str, uuid.UUID]
    ) -> None:
        set_tenant(app_conn, two_tenants["alpha"])
        app_conn.execute(
            "INSERT INTO audit_log (tenant_id, action, entity_type) VALUES (%s,'x','y')",
            (two_tenants["alpha"],),
        )
        assert app_conn.execute("SELECT count(*) FROM audit_log").fetchone()[0] == 2


class TestApplicationRoleCannotEscape:
    """RLS is only as strong as the role. A superuser or BYPASSRLS role ignores it."""

    def test_role_is_neither_superuser_nor_bypassrls(self, app_conn: psycopg.Connection) -> None:
        is_super, bypasses_rls = app_conn.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        assert not is_super
        assert not bypasses_rls

    def test_role_cannot_run_ddl(self, app_conn: psycopg.Connection) -> None:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute("CREATE TABLE escape_hatch (id int)")

    def test_role_cannot_disable_a_policy(
        self, app_conn: psycopg.Connection, two_tenants: dict[str, uuid.UUID]
    ) -> None:
        set_tenant(app_conn, two_tenants["alpha"])
        with pytest.raises(psycopg.errors.Error):
            app_conn.execute("ALTER TABLE asset DISABLE ROW LEVEL SECURITY")


class TestConnectionPoolSafety:
    def test_tenant_context_does_not_survive_commit(
        self, app_conn: psycopg.Connection, two_tenants: dict[str, uuid.UUID]
    ) -> None:
        """The reason set_config is called with is_local=true.

        A session-scoped setting would persist on the physical connection, return to
        the pool, and hand one tenant's identity to the next request that borrows it.
        """
        set_tenant(app_conn, two_tenants["alpha"])
        assert app_conn.execute("SELECT count(*) FROM asset").fetchone()[0] == 1
        app_conn.commit()
        assert app_conn.execute("SELECT count(*) FROM asset").fetchone()[0] == 0


class TestSchemaInvariants:
    def test_every_tenant_scoped_table_has_a_policy(self, app_conn: psycopg.Connection) -> None:
        """Guards against the most likely future mistake: adding a model with a
        tenant_id and forgetting the policy. Caught here rather than by a customer."""
        from app.models import ASSET_SUBTYPE_TABLES, TENANT_SCOPED_TABLES

        protected = {
            row[0]
            for row in app_conn.execute("SELECT DISTINCT tablename FROM pg_policies").fetchall()
        }
        missing = (set(TENANT_SCOPED_TABLES) | set(ASSET_SUBTYPE_TABLES)) - protected
        assert not missing, f"tables without an RLS policy: {sorted(missing)}"

    def test_policies_are_forced_so_the_owner_cannot_bypass_them(
        self, app_conn: psycopg.Connection
    ) -> None:
        unforced = app_conn.execute(
            """SELECT relname FROM pg_class
               WHERE relrowsecurity AND NOT relforcerowsecurity
                 AND relnamespace = 'public'::regnamespace"""
        ).fetchall()
        assert not unforced, f"RLS enabled but not FORCEd: {unforced}"
