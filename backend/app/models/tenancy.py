"""The tenant table — the root of the isolation hierarchy."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An isolated organisation. Every other tenant-scoped row points here.

    This table is deliberately *not* tenant-scoped and carries no RLS policy: a row
    here defines a tenant rather than belonging to one. Access is mediated by the
    application, never by ``current_setting('otgp.tenant_id')``.
    """

    __tablename__ = "tenant"

    # Used in URLs and as the OIDC/SAML organisation hint, so it is constrained to a
    # DNS-label-safe shape rather than merely "unique".
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # server_default, not just default: a NOT NULL column whose default lives only in
    # Python breaks every write that does not go through the ORM — psql, COPY, Celery
    # tasks issuing raw SQL, and data migrations.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    __table_args__ = (
        CheckConstraint(
            r"slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'",
            name="slug_is_dns_label",
        ),
    )

    def __repr__(self) -> str:
        return f"<Tenant {self.slug}>"
