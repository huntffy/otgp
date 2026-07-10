"""Behavioural contract for resolve_effective_permissions().

Pure unit tests: no database, no fixtures, no I/O. Authorisation decisions are the one
place in the system where a subtle bug is both silent and severe, so the logic is kept
free of anything that could make a test slow enough to be skipped.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.permissions import (
    ALL_PERMISSIONS,
    PermissionDeniedError,
    Principal,
    RoleGrant,
    require,
    resolve_effective_permissions,
)

TENANT = uuid.uuid4()
PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()


def principal(*grants: RoleGrant, active: bool = True, admin: bool = False) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=TENANT,
        is_active=active,
        is_tenant_admin=admin,
        grants=grants,
    )


def grant(*codes: str, project: uuid.UUID | None = None) -> RoleGrant:
    return RoleGrant(role_id=uuid.uuid4(), project_id=project, permission_codes=frozenset(codes))


class TestDeactivation:
    def test_inactive_user_holds_nothing_despite_roles(self) -> None:
        """Deactivation must be immediate and total, not merely a login block."""
        p = principal(grant("project:read", "asset:write"), active=False)
        assert resolve_effective_permissions(p, PROJECT_A) == frozenset()

    def test_inactive_tenant_admin_holds_nothing(self) -> None:
        """The admin bypass must sit *behind* the active check, not in front of it."""
        p = principal(active=False, admin=True)
        assert resolve_effective_permissions(p, PROJECT_A) == frozenset()


class TestTenantAdmin:
    def test_tenant_admin_holds_every_permission(self) -> None:
        p = principal(admin=True)
        assert resolve_effective_permissions(p, PROJECT_A) == ALL_PERMISSIONS

    def test_tenant_admin_holds_every_permission_at_tenant_scope(self) -> None:
        p = principal(admin=True)
        assert resolve_effective_permissions(p, None) == ALL_PERMISSIONS


class TestTenantWideGrants:
    def test_tenant_wide_grant_applies_to_any_project(self) -> None:
        p = principal(grant("asset:write"))
        assert "asset:write" in resolve_effective_permissions(p, PROJECT_A)
        assert "asset:write" in resolve_effective_permissions(p, PROJECT_B)

    def test_tenant_wide_grant_applies_to_tenant_level_operations(self) -> None:
        p = principal(grant("project:write"))
        assert "project:write" in resolve_effective_permissions(p, None)


class TestProjectScopedGrants:
    def test_project_grant_applies_only_to_that_project(self) -> None:
        p = principal(grant("asset:write", project=PROJECT_A))
        assert "asset:write" in resolve_effective_permissions(p, PROJECT_A)
        assert "asset:write" not in resolve_effective_permissions(p, PROJECT_B)

    def test_project_grant_does_not_leak_into_tenant_scope(self) -> None:
        """Otherwise an Engineer on one project could create projects tenant-wide."""
        p = principal(grant("project:write", project=PROJECT_A))
        assert resolve_effective_permissions(p, None) == frozenset()


class TestCombination:
    def test_multiple_grants_union(self) -> None:
        p = principal(grant("project:read"), grant("asset:write", project=PROJECT_A))
        assert resolve_effective_permissions(p, PROJECT_A) == frozenset(
            {"project:read", "asset:write"}
        )

    def test_no_grants_means_no_permissions(self) -> None:
        assert resolve_effective_permissions(principal(), PROJECT_A) == frozenset()

    def test_narrower_grant_never_removes_a_broader_one(self) -> None:
        """Union semantics: there is no deny-list and no precedence order."""
        p = principal(grant("asset:read", "asset:write"), grant("asset:read", project=PROJECT_A))
        assert "asset:write" in resolve_effective_permissions(p, PROJECT_A)


class TestRequire:
    def test_require_passes_when_permission_is_held(self) -> None:
        require(principal(grant("asset:read")), "asset:read", PROJECT_A)

    def test_require_raises_when_permission_is_absent(self) -> None:
        with pytest.raises(PermissionDeniedError) as excinfo:
            require(principal(), "asset:read", PROJECT_A)
        assert excinfo.value.permission == "asset:read"

    def test_require_rejects_an_unknown_permission_code(self) -> None:
        """A typo must fail loudly rather than evaluate to a plausible-looking 403."""
        with pytest.raises(ValueError, match="unknown permission code"):
            require(principal(admin=True), "asset:wirte", PROJECT_A)
