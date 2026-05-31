"""phase2: feature store and universe tables

Revision ID: 202605291300
Revises: 202605291200
Create Date: 2026-05-29 13:00:00+00:00

Creates:
- feature_registry: catalog of feature definitions
- feature_materialization_runs: tracks backfill/materialization runs
- universe: bitemporal membership tracking
- security_master: canonical symbol registry
- security_alias: external identifier resolution
- pit_latest() function: canonical PIT retrieval primitive
- researcher_ro role: read-only access for JupyterLab
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "202605291300"
down_revision: str = "202605291200"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- feature_registry ---
    op.create_table(
        "feature_registry",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("group", sa.String(64), nullable=False),
        sa.Column("entity", sa.String(16), nullable=False, server_default="symbol"),
        sa.Column("dtype", sa.String(32), nullable=False, server_default="numeric"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("dependencies", JSONB, nullable=True),
        sa.Column("transform_sql", sa.Text, nullable=True),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("materialization", sa.String(16), nullable=False, server_default="incremental"),
        sa.Column("freshness_sla_seconds", sa.Integer, nullable=True),
        sa.Column("knowledge_lag_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("owner", sa.String(64), nullable=True),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column("table_name", sa.String(128), nullable=False),
        sa.Column("code_commit", sa.String(40), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_feature_registry_group", "feature_registry", ["group"])
    op.create_index("ix_feature_registry_hash", "feature_registry", ["definition_hash"])

    # --- feature_materialization_runs ---
    op.create_table(
        "feature_materialization_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("feature_name", sa.String(128), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("rows_written", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_hash", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("ix_mat_run_feature", "feature_materialization_runs", ["feature_name", "started_at"])

    # --- universe ---
    op.create_table(
        "universe",
        sa.Column("universe_id", sa.String(32), primary_key=True),
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("knowledge_ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announcement_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_added", sa.Text, nullable=True),
        sa.Column("reason_removed", sa.Text, nullable=True),
        sa.Column("successor_symbol", sa.String(32), nullable=True),
    )
    op.create_index("ix_universe_lookup", "universe", ["universe_id", "effective_from", "effective_to"])
    op.create_index("ix_universe_symbol", "universe", ["symbol", "effective_from"])

    # --- security_master ---
    op.create_table(
        "security_master",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("cusip", sa.String(9), nullable=True),
        sa.Column("isin", sa.String(12), nullable=True),
        sa.Column("figi", sa.String(12), nullable=True),
        sa.Column("listed_ticker", sa.String(16), nullable=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("asset_class", sa.String(16), nullable=True),
        sa.Column("listing_exchange", sa.String(16), nullable=True),
        sa.Column("listed_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delisted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delisting_reason", sa.Text, nullable=True),
    )
    op.create_index("ix_security_master_figi", "security_master", ["figi"])

    # --- security_alias ---
    op.create_table(
        "security_alias",
        sa.Column("alias_type", sa.String(16), primary_key=True),
        sa.Column("alias_value", sa.String(32), primary_key=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("canonical_symbol", sa.String(32), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("knowledge_ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_alias_canonical", "security_alias", ["canonical_symbol", "alias_type"])

    # --- PIT retrieval function ---
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION pit_latest(
            feature_table  regclass,
            p_symbol       text,
            p_as_of        timestamptz
        ) RETURNS TABLE (event_ts timestamptz, knowledge_ts timestamptz, value numeric)
        LANGUAGE plpgsql STABLE AS $$
        BEGIN
            RETURN QUERY EXECUTE format($f$
                SELECT event_ts, knowledge_ts, value
                FROM %s
                WHERE symbol = $1
                  AND event_ts     <= $2
                  AND knowledge_ts <= $2
                ORDER BY event_ts DESC, knowledge_ts DESC, value_version DESC
                LIMIT 1
            $f$, feature_table) USING p_symbol, p_as_of;
        END $$;
    """))

    # --- Read-only researcher role ---
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'researcher_ro') THEN
                CREATE ROLE researcher_ro NOINHERIT NOLOGIN;
            END IF;
        END $$;
    """))
    op.execute(sa.text("GRANT CONNECT ON DATABASE astraeus TO researcher_ro"))
    op.execute(sa.text("GRANT USAGE ON SCHEMA public TO researcher_ro"))
    op.execute(sa.text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO researcher_ro"))
    op.execute(sa.text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO researcher_ro"))


def downgrade() -> None:
    op.execute(sa.text("DROP FUNCTION IF EXISTS pit_latest(regclass, text, timestamptz)"))
    op.execute(sa.text("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM researcher_ro"))
    op.execute(sa.text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM researcher_ro"))
    op.execute(sa.text("REVOKE USAGE ON SCHEMA public FROM researcher_ro"))
    op.execute(sa.text("REVOKE CONNECT ON DATABASE astraeus FROM researcher_ro"))
    op.execute(sa.text("DROP ROLE IF EXISTS researcher_ro"))
    op.drop_table("security_alias")
    op.drop_table("security_master")
    op.drop_table("universe")
    op.drop_table("feature_materialization_runs")
    op.drop_table("feature_registry")
