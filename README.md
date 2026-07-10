# Open Telecom GIS Planner (OTGP)

An open-source GIS platform for telecommunications engineering: RF planning, fiber
design, tower and asset management, on one extensible, plugin-driven foundation.

> **Project status: early. Phase 1 of 12.**
>
> The database foundation is built, migrated, and covered by adversarial tests against a
> real PostGIS instance. Everything else on the roadmap — the REST API, the GIS engine,
> the RF and fiber modules, the Flutter client — is **not implemented yet**.
>
> This README describes what exists today. Planned work lives in [ROADMAP.md](ROADMAP.md)
> and is clearly labelled as such. Nothing here is a stub or a placeholder: if it is in
> the source tree, it runs and it is tested.

---

## Why this project

Telecom engineers work across spreadsheets, Google Earth, CAD drawings, one-off RF
calculators, and proprietary planning tools that do not talk to each other. A link budget
lives in Excel, the tower coordinates live in a KMZ, the fiber route lives in a DWG, and
nothing reconciles. OTGP aims to be the single, open, extensible place that work can live.

The design bets:

- **PostGIS is the engine, not a storage detail.** Coverage, line-of-sight, terrain
  profiles and viewport queries are spatial problems. They belong in a spatial database.
- **Multi-tenancy is enforced by the database, not by application `WHERE` clauses.** A
  filter that must be remembered is a filter that will eventually be forgotten.
- **Every engineering calculation carries its formula, its assumptions, and its standards
  reference.** An RF number without a citation is not an engineering result.

---

## What works today

- PostgreSQL 16 + PostGIS 3.4 schema covering tenancy, IAM/RBAC, projects, an audit trail,
  and a polymorphic network-asset model.
- **Tenant isolation enforced by PostgreSQL Row-Level Security**, verified by an
  adversarial test suite that attempts to read and write across tenant boundaries.
- **An append-only audit log**, enforced by privilege revocation rather than convention.
- A reversible Alembic migration with zero drift against the ORM models
  (`alembic check` is clean).
- A Docker Compose stack: PostGIS, Redis, MinIO.

Twenty-three tests pass. Thirteen fail, all of them in `resolve_effective_permissions()`,
which is deliberately unimplemented — see [Contributing](#contributing).

## What does not exist yet

The REST API, the plugin SDK, the GIS import/export pipeline, every RF and fiber
calculator, the Flutter client, the AI assistant. See [ROADMAP.md](ROADMAP.md).

---

## Quick start

Requires Docker and Python 3.11+.

```bash
git clone https://github.com/<your-org>/otgp.git
cd otgp

cp .env.example .env          # then change every secret in it

docker compose up -d postgres redis minio

cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

set -a && . ../.env && set +a
.venv/bin/alembic upgrade head
.venv/bin/pytest
```

The compose stack binds Postgres to **port 5433**, not 5432. A locally installed
Postgres binds `127.0.0.1:5432` explicitly while Docker binds `*:5432`; both succeed, and
`localhost` silently reaches the local one.

---

## Architecture in one page

Full rationale, including the decisions rejected and why, is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Tenant isolation.** Every tenant-scoped table carries `tenant_id` and a
`FORCE ROW LEVEL SECURITY` policy comparing it against a transaction-local setting:

```sql
CREATE POLICY tenant_isolation ON asset
    USING      (tenant_id = NULLIF(current_setting('otgp.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('otgp.tenant_id', true), '')::uuid);
```

Three properties make this hold:

1. **`FORCE`, not merely `ENABLE`.** `ENABLE` exempts the table owner from its own
   policies, and the owner is exactly who runs migrations.
2. **The application connects as a role that is neither `SUPERUSER` nor `BYPASSRLS`.**
   Both bypass every policy. The security boundary is the database role, not the policy.
3. **The setting is transaction-local.** A session-scoped setting would outlive the
   request, return to the connection pool, and hand one tenant's identity to the next
   request that borrows the connection.

Unset context yields `NULL`, and `tenant_id = NULL` is never true. **Forgetting to set
tenant context returns zero rows, not the whole table.**

**Geometry.** Canonical storage is EPSG:4326. Distances and areas reproject to a working
CRS — usually a UTM zone — before measurement, never computed in degrees. Elevation is
modelled as numeric columns rather than a Z coordinate, because GiST indexes only the 2D
bounding box, and ground elevation and height-above-ground-level are distinct quantities.

**Assets.** Joined-table inheritance: shared identity in `asset`, subtype-specific
invariants in `tower`, `fiber_cable`, and so on. Chosen over a JSONB blob so that
`tower.height_m IS NOT NULL` is enforced by PostgreSQL rather than by whichever service
last remembered to check.

---

## Repository layout

```
backend/
  app/
    core/        settings, engine, tenant context, permissions
    models/      SQLAlchemy models; one file per bounded context
  alembic/       migrations, including RLS policies and triggers
  tests/         adversarial isolation tests, permission contract tests
deploy/
  postgres/init/ extension bootstrap, unprivileged app role
docs/
  ARCHITECTURE.md
```

---

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md).

The most useful first contribution is `resolve_effective_permissions()` in
`backend/app/core/permissions.py`. It is the one function with several defensible
designs, its behaviour is fully specified by `backend/tests/test_permissions.py`, and it
is pure — no database, no I/O.

Security issues: please read [SECURITY.md](SECURITY.md) and do not open a public issue.

## License

MIT. See [LICENSE](LICENSE).
