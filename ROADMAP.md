# Roadmap

Twelve phases, built in order. A phase is finished when its code is tested, documented,
and free of placeholders — not when it demos.

Nothing below is a promise of a date. It is a promise of an order.

| Phase | Scope | Status |
|------:|-------|--------|
| 1 | Architecture, folder structure, database design | **Done** |
| 2 | Authentication, RBAC, REST API foundation | In progress |
| 3 | GIS engine: layers, drawing, import/export, CRS transformation | Not started |
| 4 | RF module: link budget, FSPL, Fresnel, LOS, coverage, rain fade | Not started |
| 5 | Fiber module: routes, OLT/splitter planning, power budget, BOM | Not started |
| 6 | Tower and asset management | Not started |
| 7 | Reports: PDF, Excel, CSV, charts | Not started |
| 8 | Plugin SDK | Not started |
| 9 | AI assistant | Not started |
| 10 | Documentation | Continuous |
| 11 | Testing | Continuous |
| 12 | CI/CD | Not started |

## Phase 1 — Done

PostGIS schema for tenancy, IAM/RBAC, projects, audit, and network assets. Tenant
isolation enforced by Row-Level Security and verified adversarially. Append-only audit log
enforced by privilege. Reversible migration with zero ORM drift.

## Phase 2 — In progress

JWT and OAuth2 authentication, the permission resolution layer, and the first REST
endpoints. Blocked on `resolve_effective_permissions()` — see CONTRIBUTING.md.

## Phase 4 — A note on the RF module

Every calculator will ship with its formula, its assumptions, its validity range, and a
citation to the governing standard (ITU-R P.525 for free-space loss, ITU-R P.530 for
microwave link availability, ITU-R P.838 for rain attenuation, ITU-R P.526 for diffraction).

A calculator without a citation and without test vectors drawn from the standard will not
be merged. Engineers make load-bearing decisions with these numbers.

## Deliberately deferred

Digital twin, drone photogrammetry, SNMP telemetry, the plugin marketplace, and SDKs for
five languages are all in the long-term vision. They are not on this roadmap yet, because
listing them would imply work is underway. It is not.
