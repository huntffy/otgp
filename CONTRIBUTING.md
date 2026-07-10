# Contributing to OTGP

Thank you for considering a contribution. This project is early, which means the decisions
being made now will constrain everything built later. Careful review matters more than
speed.

## Ground rules

1. **No placeholder code.** If it is merged, it works and it is tested. A `TODO` in a
   merged pull request is a bug report with no issue number.
2. **Every engineering calculation cites its source.** An RF result without a reference to
   ITU-R, IEEE, ETSI or 3GPP is not an engineering result. Include the formula, its
   assumptions, and its validity range.
3. **Comments explain *why*, never *what*.** The code already says what it does. Explain
   the constraint the code cannot express, or say nothing.
4. **Tests must be able to fail.** A test that passes against a broken implementation is
   worse than no test, because it certifies the bug.

## Getting set up

See the Quick start in [README.md](README.md). You will need Docker and Python 3.11+.

The test suite runs against a real PostGIS database. It is not mocked, and it will not be:
Row-Level Security, GiST indexes and trigger behaviour cannot be exercised against SQLite,
and those are exactly the parts of this schema most worth testing.

```bash
docker compose up -d postgres
cd backend
set -a && . ../.env && set +a
.venv/bin/alembic upgrade head
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

## A good first contribution

`resolve_effective_permissions()` in `backend/app/core/permissions.py` is unimplemented on
purpose. It is the one function in the codebase with several defensible designs. Its
behaviour is fully specified by `backend/tests/test_permissions.py` — thirteen tests that
currently fail. It is pure: no database, no I/O.

The decisions it encodes:

- Does deactivating a user revoke authority immediately, or only block new logins?
- Does the tenant-admin bypass sit in front of the active check, or behind it?
- Does a project-scoped role leak into tenant-level operations like "create a project"?
- Do multiple roles union, or does a narrower one take precedence?

## Touching the database

Any model change needs a migration, and `alembic check` must report no drift:

```bash
.venv/bin/alembic revision --autogenerate -m "what changed"
.venv/bin/alembic upgrade head
.venv/bin/alembic check          # must print "No new upgrade operations detected."
.venv/bin/alembic downgrade base && .venv/bin/alembic upgrade head   # must round-trip
```

**A new table with a `tenant_id` needs a Row-Level Security policy.** Add it to the
migration, and add the table to `TENANT_SCOPED_TABLES` in `backend/app/models/__init__.py`.
`test_every_tenant_scoped_table_has_a_policy` will fail if you forget — which is the point.

Autogenerate does not see RLS policies, triggers, grants, or partial-index predicates.
Write those by hand and test them.

## Pull requests

- One logical change per pull request.
- The description explains *why*, and what you rejected. `git log` will outlive your memory.
- New behaviour arrives with tests. Bug fixes arrive with a test that fails without the fix.
- Public functions carry a docstring stating what the caller may rely on.

## Reporting security issues

Do not open a public issue. See [SECURITY.md](SECURITY.md).

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
