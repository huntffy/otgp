# Security Policy

## Reporting a vulnerability

**Do not open a public issue.**

Report privately via GitHub's [private vulnerability reporting][gh] on this repository.
If that is unavailable, contact the maintainers listed in `MAINTAINERS.md`.

Please include: what you can access that you should not, the steps to reproduce it, and
the commit you tested against. We will acknowledge within 72 hours and keep you updated
until the issue is resolved or declined, with reasons.

[gh]: https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability

## Supported versions

The project is pre-1.0. Only `main` receives fixes.

## The threat this project takes most seriously

OTGP is multi-tenant. A cross-tenant read is the worst failure this system can have: tower
coordinates, link budgets and network topology are commercially sensitive, and in some
deployments the physical locations are safety-sensitive.

Isolation is enforced by PostgreSQL Row-Level Security rather than by application query
predicates, because a filter that must be remembered is a filter that will eventually be
forgotten. See ADR-001 in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

The guarantee rests on three properties. Any change that breaks one is a vulnerability,
even if no data has leaked yet:

1. Every tenant-scoped table has a `FORCE ROW LEVEL SECURITY` policy.
   `ENABLE` alone exempts the table owner.
2. The application connects as a role that is neither `SUPERUSER` nor `BYPASSRLS`.
   Both bypass every policy. **The security boundary is the database role.**
3. Tenant context is set transaction-locally. A session-scoped setting outlives the
   request and leaks into the next one to borrow that pooled connection.

`backend/tests/test_tenant_isolation.py` attempts to violate each of these. Treat a
failure there as a security incident, not a broken test.

## Deployment expectations

- Never run the application as the schema owner or as a superuser. Migrations use a
  separate connection string (`OTGP_MIGRATION_DATABASE_URL`) for exactly this reason.
- Change every credential in `.env.example` before any deployment.
- `audit_log` is append-only by privilege revocation. Do not re-grant `UPDATE` or
  `DELETE` on it to the application role.
