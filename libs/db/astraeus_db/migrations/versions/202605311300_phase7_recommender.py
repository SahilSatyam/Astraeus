"""phase7: Daily recommendation engine — pipeline runs, signals, ensemble, HITL

Revision ID: 202605311300
Revises: 202605311200
Create Date: 2026-05-31 13:00:00+00:00

Creates:
- recommender_run: pipeline run tracking
- regime_state: regime detection results per run
- signal_value: per-signal scores per (run, signal, ticker)
- ensemble_weight: regime-conditional weights per run
- recommendation: final recommendations with lifecycle state
- recommendation_decision: HITL decisions with override capture
- risk_rejection: risk gate rejection log
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "202605311300"
down_revision: str = "202605311200"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- recommender_run ---
    op.create_table(
        "recommender_run",
        sa.Column("run_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("input_snapshot_hash", sa.LargeBinary(), nullable=False),
        sa.Column("code_commit", sa.String(64), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_recommender_run_date", "recommender_run", ["run_date"])
    op.create_index("ix_recommender_run_status", "recommender_run", ["status"])

    # --- regime_state ---
    op.create_table(
        "regime_state",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("model", sa.String(32), nullable=False, server_default="hmm_v1"),
        sa.ForeignKeyConstraint(["run_id"], ["recommender_run.run_id"], name="fk_regime_state_run"),
    )
    op.create_index("ix_regime_state_run_id", "regime_state", ["run_id"])
    op.create_index("ix_regime_state_label", "regime_state", ["label"])

    # --- signal_value ---
    op.create_table(
        "signal_value",
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("signal", sa.String(32), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_z", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "signal", "ticker"),
        sa.ForeignKeyConstraint(["run_id"], ["recommender_run.run_id"], name="fk_signal_value_run"),
    )
    op.create_index("ix_signal_value_ticker", "signal_value", ["ticker"])

    # --- ensemble_weight ---
    op.create_table(
        "ensemble_weight",
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("signal", sa.String(32), nullable=False),
        sa.Column("regime", sa.String(32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "signal", "regime"),
        sa.ForeignKeyConstraint(["run_id"], ["recommender_run.run_id"], name="fk_ensemble_weight_run"),
    )

    # --- recommendation ---
    op.create_table(
        "recommendation",
        sa.Column("rec_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("target_weight", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=False),
        sa.Column("component_attribution", JSONB, nullable=False),
        sa.Column("risk_passed", sa.Boolean(), nullable=False),
        sa.Column("risk_notes", JSONB, nullable=True),
        sa.Column("thesis_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("side IN ('long', 'short', 'flat')", name="ck_recommendation_side"),
        sa.ForeignKeyConstraint(["run_id"], ["recommender_run.run_id"], name="fk_recommendation_run"),
    )
    op.create_index("ix_recommendation_run_id", "recommendation", ["run_id"])
    op.create_index("ix_recommendation_state", "recommendation", ["state"])
    op.create_index("ix_recommendation_ticker", "recommendation", ["ticker"])

    # --- recommendation_decision ---
    op.create_table(
        "recommendation_decision",
        sa.Column("rec_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_by", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("override_weight", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("rec_id", "decided_at"),
        sa.ForeignKeyConstraint(["rec_id"], ["recommendation.rec_id"], name="fk_decision_rec"),
    )

    # --- risk_rejection ---
    op.create_table(
        "risk_rejection",
        sa.Column("rec_id", UUID(as_uuid=True), nullable=False),
        sa.Column("rule", sa.String(64), nullable=False),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("rec_id", "rule"),
    )


def downgrade() -> None:
    op.drop_table("risk_rejection")
    op.drop_table("recommendation_decision")
    op.drop_table("recommendation")
    op.drop_table("ensemble_weight")
    op.drop_table("signal_value")
    op.drop_table("regime_state")
    op.drop_table("recommender_run")
