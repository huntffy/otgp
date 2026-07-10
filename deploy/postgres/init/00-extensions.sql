-- Executed once, by the postgres image, on first cluster initialisation.
-- Runs as the superuser defined by POSTGRES_USER.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;

-- Trigram indexes back the case-insensitive "search assets by name/serial" queries.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- btree_gist lets a single index mix a scalar (tenant_id) with a geometry,
-- which is what every tenant-scoped viewport query needs.
CREATE EXTENSION IF NOT EXISTS btree_gist;
