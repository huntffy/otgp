# Architecture

This document records the decisions that are expensive to reverse, and why the rejected
alternatives were rejected. Decisions that are cheap to change are not recorded here.

Status: Phase 1 of 12 is implemented. Sections describing later phases state the intended
design and say plainly that it is not yet built.

---

## ADR-001 — Tenant isolation via shared schema and Row-Level Security

**Status:** implemented and tested.

**Context.** OTGP must serve many organisations from one deployment. An operator's tower
coordinates and link budgets are commercially sensitive; a cross-tenant read is the worst
failure this system can have.

**Decision.** One set of tables. Every tenant-scoped row carries `tenant_id`. PostgreSQL
Row-Level Security enforces the boundary.

**Alternatives rejected.**

- *Schema per tenant.* Strong isolation, easy per-tenant restore. Rejected: every
  migration runs N times, and PostgreSQL's catalogue degrades past a few thousand schemas.
- *Database per tenant.* Maximum isolation. Rejected: connection-pool pressure, heavy
  operations, cross-tenant analytics become impractical.
- *Application-level `WHERE tenant_id = ?`.* Rejected outright. It relies on every query
  written by every future contributor being correct. One forgotten clause is a breach.

**Consequences, and the three things that make it actually work.**

1. **`FORCE ROW LEVEL SECURITY`, not just `ENABLE`.** `ENABLE` exempts the table *owner*
   from its own policies. In a naive setup the application connects as the owner, so RLS
   silently does nothing. `FORCE` subjects the owner too.

2. **The application connects as a role that is neither superuser nor `BYPASSRLS`.**
   Both bypass every policy unconditionally, and `FORCE` does not change that. Migrations
   run as the owner (`otgp`); requests run as `otgp_app`, which has no DDL rights.
   *The security boundary is the database role, not the policy.*

3. **Tenant context is transaction-local.**

   ```sql
   SELECT set_config('otgp.tenant_id', $1, true);   -- is_local => true
   ```

   With `is_local => false` the setting persists on the physical connection after the
   request ends. That connection returns to the pool and the next request — possibly a
   different tenant — inherits it. `COMMIT` and `ROLLBACK` both clear a transaction-local
   setting, so there is no path that leaves it set.

   `set_config()` rather than `SET LOCAL` because `SET` is parsed before bind parameters
   exist, so the tenant id would have to be interpolated into the SQL string.

**Fail-closed.** `current_setting('otgp.tenant_id', true)` returns `NULL` when unset, and
`tenant_id = NULL` is never true. A request that forgets tenant context reads **zero
rows**, not every row. The two-argument form is the difference between a bug and a breach.

**Joined-inheritance subtypes need their own policies.** RLS protects tables, not object
graphs. PostgreSQL does not know `tower` is part of `asset`, so a policy on `asset` does
nothing for `SELECT * FROM tower`. Subtype tables carry a policy whose `EXISTS` subquery
reads the parent — and that subquery is itself subject to the parent's policy, so
isolation composes rather than being duplicated. Cost: one primary-key lookup.

Verified by `backend/tests/test_tenant_isolation.py`, which attempts cross-tenant reads
and writes, hostile `WHERE` clauses, policy disabling, DDL, and connection reuse.

---

## ADR-002 — The audit log is append-only, enforced by privilege

**Status:** implemented and tested.

**Decision.** `audit_log` grants the application role `SELECT` and `INSERT`. `UPDATE`,
`DELETE` and `TRUNCATE` are revoked.

**The subtlety this exists to document.** It is tempting to write RLS policies for only
`SELECT` and `INSERT` and conclude that the other verbs are therefore denied. They are
not. Under RLS an `UPDATE` with no matching policy **does not raise** — it matches zero
rows and commits as a silent no-op. The caller cannot distinguish "tampering blocked" from
"row absent," and monitoring sees nothing.

**RLS filters rows; `GRANT` controls verbs.** Only a privilege revocation raises
`InsufficientPrivilege`, which is what turns a tamper attempt into a signal.

Deleting a tenant still cascades into `audit_log`, because referential-integrity actions
run internally and are not subject to either mechanism. Append-only for the application;
still erasable for a lawful deletion request.

---

## ADR-003 — Canonical geometry storage is EPSG:4326

**Status:** implemented.

**Decision.** Every geometry column is `geometry(..., 4326)` — WGS84 lat/lon.

**Rationale.** It matches GPS, GeoJSON, KML, GPX and every import format the platform must
ingest. Interchange is the common case; measurement is the special case.

**Alternatives rejected.**

- *EPSG:3857 (Web Mercator).* Renders to OSM/MapLibre tiles without reprojection.
  Rejected: distances and areas are badly distorted away from the equator. This platform's
  core purpose is computing RF path lengths and clearances. A projection that lies about
  distance is disqualifying.
- *PostGIS `geography` type.* True spheroidal distance for free. Rejected as the default:
  a much smaller function surface and slower planar analysis. It remains available by cast
  where exact great-circle distance matters.

**Consequence.** `project.display_srid` records the CRS engineers *work* in — typically a
UTM zone, where a metre is a metre. Storage stays 4326; only presentation and metric
computation reproject. Separating the two is what prevents computing a path length in
degrees.

**Elevation is not stored in the geometry.** `POINT`, not `POINTZ`. GiST indexes only the
2D bounding box, DEM-derived ground elevation changes whenever the elevation source is
swapped, and ground elevation is a different quantity from an antenna's height above
ground level. A Z coordinate would conflate them. Both are numeric columns.

---

## ADR-004 — Assets use joined-table inheritance

**Status:** implemented for the base table and one subtype (`tower`).

**Decision.** Shared identity, geometry, and audit columns live in `asset`. Subtype-specific
columns live in their own table keyed by the same UUID.

**Alternative rejected: one wide table with a JSONB `properties` column.** Adding an asset
type would need no migration, and plugins could define types freely. Rejected because it
cannot express `tower.height_m IS NOT NULL` — a fiber cable has no height, so every
subtype column would have to be nullable, and the invariant would migrate out of the
database and into whichever service last remembered to check it. A typo'd property key
fails silently at 02:00.

**Cost accepted.** A join on read, and a migration per new asset type. Plugin-defined
asset types will be addressed in Phase 8 by letting a plugin ship its own migration,
not by weakening the core schema.

---

## ADR-005 — Indexing for 100,000+ objects

**Status:** implemented.

The query that must never be slow is the viewport fetch, run on every map pan:

```sql
SELECT … FROM asset
WHERE tenant_id = :tenant AND location && ST_MakeEnvelope(…, 4326) AND deleted_at IS NULL;
```

It is served by a single index:

```sql
CREATE INDEX ix_asset_tenant_id_location ON asset USING gist (tenant_id, location)
    WHERE deleted_at IS NULL;
```

A GiST index cannot normally include a scalar like `tenant_id`; the `btree_gist`
extension supplies B-tree operator classes for scalars inside a GiST index. Without it
PostgreSQL needs two separate indexes and a bitmap AND, which is materially slower.

The index is **partial** (`WHERE deleted_at IS NULL`), so tombstoned rows cost nothing.
Uniqueness constraints on soft-deletable tables are partial for the same reason: deleting
a tower releases its code for reuse without severing the audit log's reference to it.

`pg_trgm` backs case-insensitive substring search over asset names.

---

## ADR-006 — Defaults live in the database, not only in Python

**Status:** implemented.

SQLAlchemy's `default=` is a Python value injected into the `INSERT` the ORM builds.
`server_default=` is DDL. Anything writing without the ORM — `psql`, `COPY`, a Celery task,
a data migration — sees only the latter. Every `NOT NULL` column with a default declares
both.

`updated_at` is maintained by a trigger rather than SQLAlchemy's `onupdate`, for the same
reason: a bulk `UPDATE` in raw SQL must not leave a stale timestamp.

`Enum(..., values_callable=...)` persists the member *value* (`"planned"`), not its name
(`"PLANNED"`). Without it the database and every JSON payload disagree.

---

## Layering

```
api/          HTTP surface. Validates, authorises, delegates. No business logic.   [Phase 2]
services/     Engineering and orchestration. Pure where possible.                  [Phase 2]
repositories/ Data access. The only layer that knows SQLAlchemy.                   [Phase 2]
models/       SQLAlchemy tables and their invariants.                          [implemented]
core/         Settings, engine, tenant context, permissions.                   [implemented]
plugins/      Third-party extension host.                                          [Phase 8]
workers/      Celery tasks: imports, heatmaps, report rendering.                    [Phase 7]
```

Authorisation is decided by `core/permissions.py`, which performs **no I/O**. Callers load
role grants through a tenant-scoped session — so RLS has already discarded other tenants'
rows — and pass them in. A pure decision function is exhaustively testable, and
authorisation is the one place where a subtle bug is both silent and severe.

---

## Not yet designed

The GIS import/export pipeline (ADR-007), the plugin isolation and permission model
(ADR-008), and offline synchronisation and conflict resolution (ADR-009) are unwritten.
They will be added before the code they describe, not after.
