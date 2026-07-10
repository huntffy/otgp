# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Database foundation (Phase 1): tenancy, IAM/RBAC, projects, audit log, and a polymorphic
  network-asset model on PostgreSQL 16 + PostGIS 3.4.
- Multi-tenant isolation via `FORCE ROW LEVEL SECURITY`, with transaction-local tenant
  context and a dedicated unprivileged application role (`NOSUPERUSER`, `NOBYPASSRLS`).
- Append-only `audit_log`, enforced by revoking `UPDATE`, `DELETE` and `TRUNCATE` from the
  application role rather than by relying on the absence of an RLS policy.
- Adversarial tenant-isolation test suite: cross-tenant reads and writes, hostile `WHERE`
  clauses, policy disabling, DDL attempts, and connection-pool reuse.
- Composite GiST index `(tenant_id, location)` via `btree_gist`, partial on `deleted_at IS
  NULL`, serving the viewport query from a single index.
- Reversible Alembic migration with no drift against the ORM models.
- Docker Compose stack: PostGIS, Redis, MinIO.

### Known gaps

- `resolve_effective_permissions()` is unimplemented; its thirteen contract tests fail.
- No REST API, GIS engine, RF module, fiber module, plugin SDK, or Flutter client yet.
  See [ROADMAP.md](ROADMAP.md).
