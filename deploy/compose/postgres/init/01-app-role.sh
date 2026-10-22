#!/usr/bin/env bash
# Creates the non-superuser role the API connects as. Superusers bypass row-level
# security, so the app must never connect as POSTGRES_USER. Grants are applied by
# the Alembic migrations; this script only creates the login role.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_user="$APP_DB_USER" -v app_password="$APP_DB_PASSWORD" <<-'EOSQL'
	CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password' NOSUPERUSER NOBYPASSRLS;
	GRANT CONNECT ON DATABASE :"DBNAME" TO :"app_user";
	CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
