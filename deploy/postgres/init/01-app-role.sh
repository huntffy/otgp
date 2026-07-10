#!/bin/bash
# Creates the unprivileged role the application connects as.
#
# This role is the security boundary for multi-tenancy. It is deliberately neither
# the owner of the tables nor a superuser, because both of those bypass Row-Level
# Security:
#
#   * a superuser bypasses every policy, unconditionally;
#   * a table owner bypasses policies unless the table is FORCE ROW LEVEL SECURITY.
#
# Migrations run as POSTGRES_USER (the owner). Requests run as APP_DB_USER.
# Never merge the two.
#
# Executed once, by the postgres image, on first cluster initialisation.

set -euo pipefail

: "${APP_DB_USER:?APP_DB_USER must be set}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be set}"

psql_super() {
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" "$@"
}

role_exists=$(psql_super -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${APP_DB_USER}'")

if [ "$role_exists" != "1" ]; then
    # :'pw' is interpolated and safely quoted by psql, so the password is never
    # concatenated into SQL by the shell.
    #
    # It must arrive on stdin, not via `psql -c`: with -c the string is handed
    # straight to the server and psql performs no variable substitution at all.
    psql_super -v pw="$APP_DB_PASSWORD" <<-SQL
	    CREATE ROLE "${APP_DB_USER}" LOGIN PASSWORD :'pw'
	        NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
	SQL
fi

psql_super <<-SQL
    GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO "${APP_DB_USER}";
    GRANT USAGE ON SCHEMA public TO "${APP_DB_USER}";

    -- ST_Transform and friends read spatial_ref_sys.
    GRANT SELECT ON TABLE public.spatial_ref_sys TO "${APP_DB_USER}";

    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "${APP_DB_USER}";
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "${APP_DB_USER}";

    -- Applies to tables the migration owner creates from now on.
    ALTER DEFAULT PRIVILEGES FOR ROLE "${POSTGRES_USER}" IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "${APP_DB_USER}";
    ALTER DEFAULT PRIVILEGES FOR ROLE "${POSTGRES_USER}" IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO "${APP_DB_USER}";

    -- The application role must never gain DDL rights.
    REVOKE CREATE ON SCHEMA public FROM "${APP_DB_USER}";
SQL
