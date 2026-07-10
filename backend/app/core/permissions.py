"""Resolving what a user is allowed to do.

Permissions reach a user along two independent paths:

  * tenant-wide, via ``user_role`` — an Engineer on every project in the tenant;
  * project-scoped, via ``project_member`` — an Engineer on exactly one project.

Both paths point at the same tenant-owned ``role`` rows, so an organisation defines
"Engineer" once. Effective authority for a given project is derived from both, plus the
``is_tenant_admin`` escape hatch that guarantees a tenant can always repair its own
broken role configuration.

Nothing here queries the database. Callers load the relevant rows through a
tenant-scoped session — so Row-Level Security has already discarded any other tenant's
roles before this code runs — and pass them in. That keeps the policy decision pure and
therefore exhaustively testable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


class PermissionDeniedError(Exception):
    """Raised when an actor lacks the permission required for an operation."""

    def __init__(self, permission: str) -> None:
        super().__init__(f"missing permission: {permission}")
        self.permission = permission


@dataclass(frozen=True, slots=True)
class RoleGrant:
    """A role held by the user, and the project it is confined to.

    ``project_id is None`` means the grant is tenant-wide and applies to every project.
    """

    role_id: uuid.UUID
    project_id: uuid.UUID | None
    permission_codes: frozenset[str]


@dataclass(frozen=True, slots=True)
class Principal:
    """Everything needed to decide an authorisation question, loaded once per request."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    is_active: bool
    is_tenant_admin: bool
    grants: tuple[RoleGrant, ...]


def resolve_effective_permissions(
    principal: Principal,
    project_id: uuid.UUID | None,
) -> frozenset[str]:
    """Return every permission code ``principal`` holds in the scope of ``project_id``.

    Args:
        principal: The acting user, with all role grants already loaded.
        project_id: The project the operation targets, or ``None`` for tenant-level
            operations such as "create a project" or "invite a user".

    Returns:
        The set of permission codes granted. Empty means the user may do nothing.

    Expected behaviour, for the tests in ``tests/test_permissions.py`` to assert:

      * An inactive user holds no permissions, regardless of role. Deactivation must be
        immediate and total.
      * A tenant admin holds every permission within their own tenant, and never outside
        it. ``ALL_PERMISSIONS`` below is the full catalogue.
      * A tenant-wide grant (``project_id is None``) applies to every project, and to
        tenant-level operations.
      * A project-scoped grant applies only when it matches ``project_id``. It must not
        leak into tenant-level operations, or a per-project Engineer could create new
        projects.
      * Multiple grants union together. There is no deny-list and no precedence order;
        holding two roles means holding the union of their permissions.
    """
    # Deactivation is checked before anything else, including the admin bypass. A
    # disabled account must lose authority the instant the flag flips, not at its next
    # login — otherwise revoking a compromised administrator does nothing until their
    # token expires.
    if not principal.is_active:
        return frozenset()

    # The escape hatch that guarantees a tenant can always repair its own role
    # configuration. Scoped to the principal's own tenant by construction: RLS has
    # already discarded every other tenant's rows before this function is reached.
    if principal.is_tenant_admin:
        return ALL_PERMISSIONS

    granted: set[str] = set()
    for role_grant in principal.grants:
        if role_grant.project_id is None:
            # Tenant-wide: applies to every project, and to tenant-level operations.
            granted |= role_grant.permission_codes
        elif project_id is not None and role_grant.project_id == project_id:
            # Project-scoped: applies only to its own project.
            #
            # The `project_id is not None` guard is what stops a per-project Engineer
            # from creating new projects. Without it, a tenant-level question — asked
            # with project_id=None — would match every project-scoped grant the user
            # holds, silently promoting them tenant-wide.
            granted |= role_grant.permission_codes

    # Union, with no deny-list and no precedence. Deny rules read as safer than they
    # are: once two roles can contradict each other, the effective permission set
    # depends on evaluation order, and no reviewer can predict it from the role names.
    return frozenset(granted)


ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        "project:read",
        "project:write",
        "project:delete",
        "asset:read",
        "asset:write",
        "asset:delete",
        "member:read",
        "member:write",
        "role:read",
        "role:write",
        "audit:read",
    }
)


def require(
    principal: Principal,
    permission: str,
    project_id: uuid.UUID | None = None,
) -> None:
    """Assert ``principal`` holds ``permission``; raise ``PermissionDeniedError`` otherwise."""
    if permission not in ALL_PERMISSIONS:
        # A typo'd permission code must fail loudly at the call site rather than
        # quietly evaluating to "denied" and looking like a legitimate 403.
        raise ValueError(f"unknown permission code: {permission!r}")
    if permission not in resolve_effective_permissions(principal, project_id):
        raise PermissionDeniedError(permission)
