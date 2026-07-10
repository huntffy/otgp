"""Projects — the unit of collaboration, and the second scoping axis after tenant."""

from __future__ import annotations

import uuid

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Project(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin):
    """A bounded body of engineering work: a coverage study, an FTTH rollout, a link plan.

    ``area_of_interest`` is the project's working extent, stored in EPSG:4326 like every
    other geometry in the schema. It is a polygon rather than four float columns so that
    "which projects touch this point" is a GiST index lookup instead of a table scan.

    ``display_srid`` records the projection engineers *work* in — typically a UTM zone,
    where a metre is actually a metre. Storage stays 4326; only presentation and metric
    computation reproject. Keeping these separate is what prevents the classic error of
    computing a path length in degrees.
    """

    __tablename__ = "project"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user_account.id", ondelete="RESTRICT"),
        nullable=False,
    )

    area_of_interest: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
        default=None,
    )

    display_srid: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4326, server_default=text("4326")
    )

    __table_args__ = (
        CheckConstraint(
            r"slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'",
            name="slug_is_dns_label",
        ),
        Index("ix_project_tenant_id", "tenant_id"),
        # Partial, so deleting a project releases its slug for reuse without breaking
        # the audit log's reference to the tombstoned row.
        Index(
            "uq_project_tenant_id_slug",
            "tenant_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_project_area_of_interest", "area_of_interest", postgresql_using="gist"),
    )

    def __repr__(self) -> str:
        return f"<Project {self.slug}>"


class ProjectMember(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """Grants a user a role *within one project*.

    Roles reach a user by two independent paths: tenant-wide (``user_role``) and
    per-project (this table). A tenant-wide Engineer can edit every project; a
    per-project Engineer can edit exactly one. Effective permissions are the union,
    which is what ``resolve_effective_permissions`` computes.

    ``role_id`` deliberately points at the same tenant-scoped ``role`` table rather than
    a separate enum, so an organisation defines "Engineer" once and reuses it in both
    scopes.
    """

    __tablename__ = "project_member"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("role.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", "role_id", name="uq_project_member_project_id_user_id_role_id"
        ),
        Index("ix_project_member_tenant_id", "tenant_id"),
        Index("ix_project_member_user_id_project_id", "user_id", "project_id"),
    )

    def __repr__(self) -> str:
        return f"<ProjectMember user={self.user_id} project={self.project_id}>"
