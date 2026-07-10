"""SQLAlchemy models.

Importing this package registers every table on ``Base.metadata``. Alembic's
``env.py`` relies on that, so a new model file is not migrated until it is
imported here.
"""

from app.models.asset import Asset, AssetStatus, StructureType, Tower
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.iam import Permission, Role, UserAccount, role_permission, user_role
from app.models.project import Project, ProjectMember
from app.models.tenancy import Tenant

# Tables that carry a tenant_id and must therefore be protected by a Row-Level
# Security policy. The migration reads this list, and a test asserts that every
# tenant-scoped table appears in pg_policies. Adding a model without adding it here
# is caught by that test rather than by a customer.
TENANT_SCOPED_TABLES: tuple[str, ...] = (
    "user_account",
    "role",
    "project",
    "project_member",
    "asset",
    "audit_log",
)

# Joined-table inheritance subtypes. They have no tenant_id of their own; their policy
# defers to the parent row in `asset`, whose own policy does the tenant check.
ASSET_SUBTYPE_TABLES: tuple[str, ...] = ("tower",)

__all__ = [
    "ASSET_SUBTYPE_TABLES",
    "TENANT_SCOPED_TABLES",
    "Asset",
    "AssetStatus",
    "AuditLog",
    "Base",
    "Permission",
    "Project",
    "ProjectMember",
    "Role",
    "StructureType",
    "Tenant",
    "Tower",
    "UserAccount",
    "role_permission",
    "user_role",
]
