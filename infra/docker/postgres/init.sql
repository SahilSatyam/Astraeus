-- Astraeus Postgres init.
--
-- Runs once on first cluster boot via /docker-entrypoint-initdb.d.
-- Creates the analytics database; OLTP db is created via POSTGRES_DB env var.

\set ON_ERROR_STOP on

CREATE DATABASE astraeus_research OWNER astraeus;
COMMENT ON DATABASE astraeus IS 'Astraeus OLTP database (services, control plane).';
COMMENT ON DATABASE astraeus_research IS 'Astraeus research database (Timescale hypertables, Phase 1+).';
