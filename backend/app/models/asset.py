"""Network assets.

Assets use joined-table inheritance: everything a tower, a splitter and a radio share
lives in ``asset``; everything specific to a tower lives in ``tower``, keyed by the same
UUID. The alternative — one wide table with a JSONB blob — was rejected because it
cannot express ``tower.height_m IS NOT NULL``: a fiber cable has no height, so every
subtype column would have to be nullable and the invariant would move from the database
into whichever service last remembered to check it.

``Tower`` below is the reference implementation of the pattern. Remaining asset types
(antennas, radios, OLTs, splitters, patch panels, power plant) are introduced by the
phases that own them, each following exactly this shape.
"""

from __future__ import annotations

import uuid
from datetime import date
from enum import StrEnum

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
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


class AssetStatus(StrEnum):
    """Lifecycle of a physical asset. Drives which simulations may include it."""

    PLANNED = "planned"
    IN_CONSTRUCTION = "in_construction"
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    DECOMMISSIONED = "decommissioned"


class StructureType(StrEnum):
    """Physical form of a tower structure. Determines wind-load and climb procedures."""

    LATTICE = "lattice"
    MONOPOLE = "monopole"
    GUYED_MAST = "guyed_mast"
    ROOFTOP = "rooftop"
    WATER_TANK = "water_tank"
    CAMOUFLAGE = "camouflage"


class Asset(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin):
    """Base table for every physical thing the platform tracks.

    ``location`` is 2D ``POINT`` in EPSG:4326, not ``POINTZ``. Elevation is modelled as
    separate numeric columns because GiST only indexes the 2D bounding box anyway, because
    DEM-derived ground elevation changes whenever the elevation source is swapped, and
    because ground elevation and height-above-ground-level are different quantities that a
    Z coordinate would conflate.

    ``asset_type`` is a free string rather than a native Postgres enum so that plugins can
    register subtypes without an ``ALTER TYPE`` on a shared enum — which takes an ACCESS
    EXCLUSIVE lock and cannot run inside a transaction with other DDL on older servers.
    """

    __tablename__ = "asset"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )

    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Operator-facing identifier, e.g. "TWR-KBL-0147". Unique per project when live.
    code: Mapped[str] = mapped_column(String(64), nullable=False)

    location: Mapped[object] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    # Metres above mean sea level, from the DEM or a survey. Distinct from any
    # height-above-ground-level of equipment mounted on the asset.
    ground_elevation_m: Mapped[float | None] = mapped_column(Float, default=None)

    # values_callable persists the member *value* ("planned"), not its name ("PLANNED").
    # Without it SQLAlchemy stores the name, and every JSON payload would disagree with
    # every row in the database.
    status: Mapped[AssetStatus] = mapped_column(
        Enum(
            AssetStatus,
            name="asset_status",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=AssetStatus.PLANNED,
        server_default=text("'planned'"),
    )

    vendor: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=text("''")
    )
    model: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=text("''")
    )
    serial_number: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=text("''")
    )

    installed_at: Mapped[date | None] = mapped_column(Date, default=None)
    warranty_expires_at: Mapped[date | None] = mapped_column(Date, default=None)

    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))

    __mapper_args__ = {
        "polymorphic_on": "asset_type",
        "polymorphic_identity": "asset",
    }

    __table_args__ = (
        CheckConstraint(
            "ground_elevation_m IS NULL OR ground_elevation_m BETWEEN -500 AND 9000",
            name="ground_elevation_within_earth_range",
        ),
        Index("ix_asset_tenant_id", "tenant_id"),
        # The viewport query: "assets of this tenant, in this project, inside this bbox".
        # tenant_id participates in the GiST index via the btree_gist extension, so the
        # whole predicate is served by one index rather than a bitmap AND of two.
        Index(
            "ix_asset_tenant_id_location",
            "tenant_id",
            "location",
            postgresql_using="gist",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_asset_project_id_asset_type", "project_id", "asset_type"),
        Index(
            "uq_asset_project_id_code",
            "project_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Backs case-insensitive substring search over the asset browser.
        Index(
            "ix_asset_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.code}>"


class Tower(Asset):
    """A supporting structure for antennas and radios.

    Reference implementation of the joined-table pattern: the row's identity lives in
    ``asset``, the tower-specific invariants live here and are enforced by the database.
    """

    __tablename__ = "tower"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True
    )

    # Structure height above its own base, in metres. Not the same as ground elevation.
    height_m: Mapped[float] = mapped_column(Float, nullable=False)
    structure_type: Mapped[StructureType] = mapped_column(
        Enum(
            StructureType,
            name="structure_type",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    # Total mass the structure may carry, in kilograms. Enforced when mounting equipment.
    max_load_kg: Mapped[float | None] = mapped_column(Float, default=None)

    __mapper_args__ = {"polymorphic_identity": "tower"}

    __table_args__ = (
        CheckConstraint("height_m > 0 AND height_m <= 700", name="height_is_physically_plausible"),
        CheckConstraint("max_load_kg IS NULL OR max_load_kg > 0", name="max_load_is_positive"),
    )
