"""Identity and access management: users, roles, and the permission catalogue."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

# Association tables carry no surrogate key: the pair *is* the identity.
role_permission = Table(
    "role_permission",
    Base.metadata,
    Column(
        "role_id",
        PG_UUID(as_uuid=True),
        ForeignKey("role.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        PG_UUID(as_uuid=True),
        ForeignKey("permission.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)

user_role = Table(
    "user_role",
    Base.metadata,
    Column(
        "user_id",
        PG_UUID(as_uuid=True),
        ForeignKey("user_account.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        PG_UUID(as_uuid=True),
        ForeignKey("role.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base, UUIDPrimaryKeyMixin):
    """A single atomic capability, e.g. ``project:write`` or ``asset:delete``.

    This is a global catalogue, not tenant-scoped: the *set* of things the software
    can do is a property of the software, not of any customer. Tenants choose which
    of these to bundle into roles.

    Deleting a permission that a role still grants is blocked (``ondelete=RESTRICT``)
    because a dangling grant would silently widen or narrow access at the next deploy.
    """

    __tablename__ = "permission"

    # "<resource>:<action>", the only format resolve_effective_permissions() parses.
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<Permission {self.code}>"


class Role(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """A named bundle of permissions, owned by a tenant.

    ``is_system`` marks roles the platform seeds (Owner, Engineer, Viewer). They may
    be granted freely but not edited or deleted, so that an administrator cannot lock
    their own tenant out by stripping the Owner role of ``role:write``.
    """

    __tablename__ = "role"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    permissions: Mapped[list[Permission]] = relationship(secondary=role_permission, lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_role_tenant_id_name"),
        Index("ix_role_tenant_id", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class UserAccount(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """A principal that authenticates and acts.

    Named ``user_account`` because ``user`` is a reserved word in Postgres and forces
    quoting into every hand-written query forever.

    ``hashed_password`` is nullable on purpose: SSO- and LDAP-backed users never have
    a local password, and storing an empty string instead of NULL would let a bug in
    a password comparison treat "no password set" as "password matched".

    ``is_tenant_admin`` is a coarse escape hatch evaluated *before* the RBAC tables,
    so that a tenant always has someone who can repair a broken role configuration.
    It grants authority only within the owning tenant; it is never cross-tenant.
    """

    __tablename__ = "user_account"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(Text, default=None)
    full_name: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=text("''")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    is_tenant_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    roles: Mapped[list[Role]] = relationship(secondary=user_role, lazy="selectin")

    __table_args__ = (
        # Scoped to the tenant, not global: the same person may hold accounts in two
        # organisations, and one tenant must not be able to probe another's user list
        # by watching a global uniqueness violation.
        UniqueConstraint("tenant_id", "email", name="uq_user_account_tenant_id_email"),
        Index("ix_user_account_tenant_id", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<UserAccount {self.email}>"
