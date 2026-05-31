"""phase6: AI agentic layer — run traces, cost ledger, prompt registry, HITL queue

Revision ID: 202605311200
Revises: 202605291600
Create Date: 2026-05-31 12:00:00+00:00

Creates:
- agent_run: top-level workflow run metadata
- agent_step: per-agent step within a run
- llm_call_ledger: every LLM call with cost/token tracking
- tool_call_ledger: every tool invocation
- prompt_registry: versioned prompts with lifecycle
- hitl_queue: human-in-the-loop items with state machine
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "202605311200"
down_revision: str = "202605291600"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- agent_run ---
    op.create_table(
        "agent_run",
        sa.Column("run_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("inputs", JSONB, nullable=True),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("output_schema_version", sa.String(16), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), server_default="0"),
        sa.Column("duration_ms", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_run_workflow", "agent_run", ["workflow_key"])
    op.create_index("ix_agent_run_status", "agent_run", ["status"])
    op.create_index("ix_agent_run_created", "agent_run", ["created_at"])

    # --- agent_step ---
    op.create_table(
        "agent_step",
        sa.Column("step_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("inputs", JSONB, nullable=True),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), server_default="0"),
        sa.Column("duration_ms", sa.Integer(), server_default="0"),
        sa.Column("parent_step_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.run_id"], name="fk_agent_step_run"),
    )
    op.create_index("ix_agent_step_run_id", "agent_step", ["run_id"])

    # --- llm_call_ledger ---
    op.create_table(
        "llm_call_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("prompt_key", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(16), nullable=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_llm_call_run_id", "llm_call_ledger", ["run_id"])
    op.create_index("ix_llm_call_agent", "llm_call_ledger", ["agent_name"])
    op.create_index("ix_llm_call_created", "llm_call_ledger", ["created_at"])

    # --- tool_call_ledger ---
    op.create_table(
        "tool_call_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("tool_version", sa.String(16), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("response_hash", sa.String(64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_tool_call_run_id", "tool_call_ledger", ["run_id"])
    op.create_index("ix_tool_call_agent", "tool_call_ledger", ["agent_name"])

    # --- prompt_registry ---
    op.create_table(
        "prompt_registry",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("prompt_key", sa.Text(), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("schema_ref", sa.Text(), nullable=False),
        sa.Column("model_hint", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("eval_run_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("prompt_key", "version", name="uq_prompt_key_version"),
    )
    op.create_index("ix_prompt_registry_key", "prompt_registry", ["prompt_key"])
    op.create_index("ix_prompt_registry_status", "prompt_registry", ["status"])

    # --- hitl_queue ---
    op.create_table(
        "hitl_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_key", sa.String(64), nullable=False),
        sa.Column("triggered_by", sa.String(64), nullable=False),
        sa.Column("reason", JSONB, nullable=False),
        sa.Column("agent_state", JSONB, nullable=False),
        sa.Column("candidate_output", JSONB, nullable=True),
        sa.Column("priority", sa.SmallInteger(), server_default="5"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("claimed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", JSONB, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_hitl_queue_status", "hitl_queue", ["status"])
    op.create_index("ix_hitl_queue_run_id", "hitl_queue", ["run_id"])
    op.create_index("ix_hitl_queue_priority", "hitl_queue", ["priority", "created_at"])


def downgrade() -> None:
    op.drop_table("hitl_queue")
    op.drop_table("prompt_registry")
    op.drop_table("tool_call_ledger")
    op.drop_table("llm_call_ledger")
    op.drop_table("agent_step")
    op.drop_table("agent_run")
