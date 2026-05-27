#!/usr/bin/env bash
# Enable Timescale on both databases. The hypertables themselves are created by
# Phase 1 alembic migrations; Phase 0 only ensures the extension is installable.

set -euo pipefail

for db in astraeus astraeus_research; do
    psql --username "${POSTGRES_USER}" --dbname "${db}" <<-SQL
        CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
        CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL
done
