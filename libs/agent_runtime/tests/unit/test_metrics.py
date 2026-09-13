"""Unit tests for the metrics module."""

from __future__ import annotations

from astraeus_agent_runtime.metrics import (
    record_budget_alert,
    record_hitl_submit,
    record_llm_call,
    record_run_complete,
    record_step_complete,
    record_tool_call,
)


class TestMetricsRecording:
    """Test that metrics recording functions don't crash.

    These are smoke tests — actual metric values are verified via
    Prometheus scraping in integration tests.
    """

    def test_record_run_complete(self) -> None:
        record_run_complete(
            {
                "workflow_key": "trade_thesis",
                "status": "completed",
                "cost_usd": 0.25,
                "duration_ms": 5000,
            }
        )

    def test_record_step_complete(self) -> None:
        record_step_complete("research", 2500.0)

    def test_record_llm_call(self) -> None:
        record_llm_call(
            agent_name="research",
            model="claude-sonnet-4-20250514",
            status="success",
            latency_ms=1500.0,
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.01,
            cache_read_tokens=200,
        )

    def test_record_tool_call(self) -> None:
        record_tool_call("research", "search_news", "success", 50.0)

    def test_record_hitl_submit(self) -> None:
        record_hitl_submit("risk_breach", "trade_thesis")

    def test_record_budget_alert(self) -> None:
        record_budget_alert("soft", "workflow")
