"""Append-only audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantScopedMixin, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """One row per state-changing action, written in the same transaction as the change.

    Deliberately not ``TimestampMixin``: an audit row is never updated, so an
    ``updated_at`` column would be a lie. It carries ``occurred_at`` only.

    ``actor_id`` is nullable and ``ON DELETE SET NULL`` — deleting a user must not
    delete the record of what they did, and must not be blocked by it either.

    ``entity_id`` is an untyped UUID with no foreign key on purpose. A foreign key
    would forbid auditing a hard delete, which is the single event most worth auditing.

    The table is protected by an RLS policy that permits SELECT and INSERT but not
    UPDATE or DELETE, so append-only is enforced by the database rather than by
    convention. Even a compromised application role cannot rewrite history.
    """

    __tablename__ = "audit_log"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user_account.id", ondelete="SET NULL"),
        default=None,
    )

    # e.g. "asset.create", "project.delete", "role.grant"
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), default=None)

    # Field-level diff. NULL "before" means creation; NULL "after" means deletion.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    client_ip: Mapped[str | None] = mapped_column(INET, default=None)
    user_agent: Mapped[str] = mapped_column(
        String(512), nullable=False, default="", server_default=text("''")
    )

    __table_args__ = (
        Index("ix_audit_log_tenant_id", "tenant_id"),
        # The two queries the compliance UI actually runs: "what happened to this
        # object" and "what did this tenant do recently".
        Index("ix_audit_log_entity_type_entity_id", "entity_type", "entity_id"),
        Index("ix_audit_log_tenant_id_occurred_at", "tenant_id", "occurred_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.entity_type}:{self.entity_id}>"
