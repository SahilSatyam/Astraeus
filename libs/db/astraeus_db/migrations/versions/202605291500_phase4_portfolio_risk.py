"""phase4: portfolio construction and risk tables

Revision ID: 202605291500
Revises: 202605291400
Create Date: 2026-05-29 15:00:00+00:00

Creates:
- target_portfolios: versioned target portfolios per strategy per day
- portfolio_weights: per-asset weights with composite PK
- risk_reports: JSONB-rich risk metrics per portfolio
- risk_rejections: structured rejection logging with GIN index
- attribution_runs: factor-model and Brinson PnL decomposition
- factor_returns: cached Ken French data (TimescaleDB hypertable)
- task_runs: idempotency and replay tracking for pipeline tasks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "202605291500"
down_revision: str = "202605291400"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- target_portfolios ---
    op.create_table(
        "target_portfolios",
        sa.Column("portfolio_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("strategy_id", sa.Text(), nullable=False),
        sa.Column("as_of_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("nav_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("nav", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("optimizer", sa.Text(), nullable=False),
        sa.Column("optimizer_config_hash", sa.Text(), nullable=False),
        sa.Column("constraint_set_hash", sa.Text(), nullable=False),
        sa.Column("covariance_estimator", sa.Text(), nullable=False),
        sa.Column("expected_return_source", sa.Text(), nullable=False),
        sa.Column("risk_report_id", UUID(as_uuid=True), nullable=True),
        sa.Column("rejection_id", UUID(as_uuid=True), nullable=True),
        sa.Column("parent_portfolio_id", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("schema_version", sa.Text(), nullable=False, server_default="v1"),
        sa.ForeignKeyConstraint(["parent_portfolio_id"], ["target_portfolios.portfolio_id"], name="fk_target_portfolios_parent"),
        sa.CheckConstraint("status IN ('passed', 'fallback_applied', 'rejected')", name="ck_target_portfolios_status"),
        sa.UniqueConstraint("strategy_id", "as_of_ts", "version", name="uq_target_portfolios_strategy_date_version"),
    )
    op.create_index(
        "idx_target_portfolios_strategy_date",
        "target_portfolios",
        [sa.text("strategy_id"), sa.text("as_of_ts DESC")],
    )

    # --- portfolio_weights ---
    op.create_table(
        "portfolio_weights",
        sa.Column("portfolio_id", UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(10, 8), nullable=False),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("portfolio_id", "symbol", name="pk_portfolio_weights"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["target_portfolios.portfolio_id"], name="fk_portfolio_weights_portfolio"),
        sa.CheckConstraint("weight >= -1.0 AND weight <= 1.0", name="ck_portfolio_weights_range"),
    )

    # --- risk_reports ---
    op.create_table(
        "risk_reports",
        sa.Column("report_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("portfolio_id", UUID(as_uuid=True), nullable=False),
        sa.Column("as_of_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("var_95_hist", sa.Numeric(10, 6), nullable=False),
        sa.Column("var_99_hist", sa.Numeric(10, 6), nullable=False),
        sa.Column("cvar_95_hist", sa.Numeric(10, 6), nullable=False),
        sa.Column("cvar_99_hist", sa.Numeric(10, 6), nullable=False),
        sa.Column("var_95_param", sa.Numeric(10, 6), nullable=False),
        sa.Column("cvar_95_param", sa.Numeric(10, 6), nullable=False),
        sa.Column("var_95_mc", sa.Numeric(10, 6), nullable=False),
        sa.Column("cvar_95_mc", sa.Numeric(10, 6), nullable=False),
        sa.Column("stress_scenarios", JSONB(), nullable=False),
        sa.Column("cluster_concentration", JSONB(), nullable=False),
        sa.Column("sector_exposure", JSONB(), nullable=False),
        sa.Column("factor_exposure", JSONB(), nullable=False),
        sa.Column("beta", sa.Numeric(8, 6), nullable=False),
        sa.Column("effective_n_bets", sa.Numeric(8, 4), nullable=False),
        sa.Column("liquidity_5day_pct", sa.Numeric(6, 4), nullable=False),
        sa.Column("constraint_diagnostics", JSONB(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False, server_default="v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["portfolio_id"], ["target_portfolios.portfolio_id"], name="fk_risk_reports_portfolio"),
    )
    op.create_index("idx_risk_reports_portfolio", "risk_reports", ["portfolio_id"])

    # --- risk_rejections ---
    op.create_table(
        "risk_rejections",
        sa.Column("rejection_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("portfolio_id", UUID(as_uuid=True), nullable=False),
        sa.Column("signal_batch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.Text(), nullable=False),
        sa.Column("as_of_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("optimizer", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("failed_checks", JSONB(), nullable=False),
        sa.Column("full_report_id", UUID(as_uuid=True), nullable=True),
        sa.Column("fallback_action", sa.Text(), nullable=False),
        sa.Column("fallback_outcome", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["full_report_id"], ["risk_reports.report_id"], name="fk_risk_rejections_report"),
    )
    op.create_index(
        "idx_risk_rejections_strategy_date",
        "risk_rejections",
        [sa.text("strategy_id"), sa.text("as_of_ts DESC")],
    )
    op.create_index("idx_risk_rejections_batch", "risk_rejections", ["signal_batch_id"])
    op.create_index(
        "idx_risk_rejections_checks",
        "risk_rejections",
        ["failed_checks"],
        postgresql_using="gin",
    )

    # --- attribution_runs ---
    op.create_table(
        "attribution_runs",
        sa.Column("run_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("portfolio_id", UUID(as_uuid=True), nullable=False),
        sa.Column("as_of_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("total_pnl_bps", sa.Numeric(12, 4), nullable=False),
        sa.Column("factor_pnl", JSONB(), nullable=True),
        sa.Column("idio_pnl_bps", sa.Numeric(12, 4), nullable=True),
        sa.Column("sector_pnl", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["portfolio_id"], ["target_portfolios.portfolio_id"], name="fk_attribution_runs_portfolio"),
        sa.CheckConstraint("method IN ('factor_ff5_mom', 'brinson')", name="ck_attribution_runs_method"),
    )
    op.create_index(
        "idx_attribution_portfolio_date",
        "attribution_runs",
        [sa.text("portfolio_id"), sa.text("as_of_ts DESC")],
    )

    # --- factor_returns (TimescaleDB hypertable) ---
    op.execute(
        sa.text("""
            CREATE TABLE factor_returns (
                factor_date     DATE NOT NULL,
                factor_name     TEXT NOT NULL,
                daily_return    NUMERIC(10, 8) NOT NULL,
                source          TEXT NOT NULL DEFAULT 'ken_french',
                ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (factor_date, factor_name)
            )
        """)
    )
    op.execute(
        sa.text(
            "SELECT create_hypertable('factor_returns', 'factor_date', "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        )
    )

    # --- task_runs ---
    op.create_table(
        "task_runs",
        sa.Column("task_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("strategy_id", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("task_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("result_hash", sa.Text(), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.UniqueConstraint("strategy_id", "as_of_date", "task_name", "version", name="uq_task_runs_strategy_date_task_version"),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed', 'timed_out')", name="ck_task_runs_status"),
    )
    op.create_index(
        "idx_task_runs_lookup",
        "task_runs",
        [sa.text("strategy_id"), sa.text("as_of_date"), sa.text("task_name"), sa.text("version DESC")],
    )


def downgrade() -> None:
    op.drop_table("task_runs")
    op.execute(sa.text("DROP TABLE IF EXISTS factor_returns CASCADE"))
    op.drop_table("attribution_runs")
    op.drop_table("risk_rejections")
    op.drop_table("risk_reports")
    op.drop_table("portfolio_weights")
    op.drop_table("target_portfolios")
