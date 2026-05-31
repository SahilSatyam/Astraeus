"""Golden tasks — curated regression suite for prompt PRs.

Each golden task defines:
- A workflow + inputs
- Assertions on the output (schema valid, citations present, cost/latency bounds)

Run on every prompt PR to catch regressions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GoldenTaskAssertion:
    """A single assertion on a golden task output."""

    name: str
    check: str  # "schema_valid", "has_citations", "cost_under", "latency_under", "field_present", "hitl_triggered"
    threshold: float | str | None = None


@dataclass(frozen=True, slots=True)
class GoldenTask:
    """A curated test case for the eval suite."""

    id: str
    name: str
    workflow: str
    inputs: dict[str, Any]
    assertions: list[GoldenTaskAssertion] = field(default_factory=list)
    description: str = ""


# --- Golden Task Definitions ---

GOLDEN_TASKS: list[GoldenTask] = [
    GoldenTask(
        id="aapl_trade_thesis",
        name="AAPL Trade Thesis",
        workflow="trade_thesis",
        inputs={"ticker": "AAPL", "lookback_days": 30, "focus": "services growth"},
        assertions=[
            GoldenTaskAssertion(name="schema_valid", check="schema_valid"),
            GoldenTaskAssertion(name="has_findings", check="field_present", threshold="research.findings"),
            GoldenTaskAssertion(name="min_3_findings", check="min_count", threshold="3"),
            GoldenTaskAssertion(name="has_citations", check="has_citations"),
            GoldenTaskAssertion(name="cost_under_50c", check="cost_under", threshold=0.50),
            GoldenTaskAssertion(name="latency_under_60s", check="latency_under", threshold=60000),
        ],
        description="Full trade thesis for AAPL with services growth focus.",
    ),
    GoldenTask(
        id="tsla_post_earnings_sentiment",
        name="TSLA Post-Earnings Sentiment",
        workflow="trade_thesis",
        inputs={"ticker": "TSLA", "lookback_days": 7, "focus": "post-earnings reaction"},
        assertions=[
            GoldenTaskAssertion(name="schema_valid", check="schema_valid"),
            GoldenTaskAssertion(name="has_sentiment", check="field_present", threshold="sentiment"),
            GoldenTaskAssertion(name="has_citations", check="has_citations"),
            GoldenTaskAssertion(name="cost_under_50c", check="cost_under", threshold=0.50),
        ],
        description="Post-earnings sentiment analysis for TSLA.",
    ),
    GoldenTask(
        id="daily_market_brief",
        name="Daily Market Brief",
        workflow="daily_brief",
        inputs={"ticker": "SPY", "lookback_days": 1},
        assertions=[
            GoldenTaskAssertion(name="schema_valid", check="schema_valid"),
            GoldenTaskAssertion(name="has_research", check="field_present", threshold="research"),
            GoldenTaskAssertion(name="cost_under_50c", check="cost_under", threshold=0.50),
        ],
        description="Daily market brief covering macro and sectors.",
    ),
    GoldenTask(
        id="portfolio_commentary",
        name="Portfolio Commentary",
        workflow="portfolio_commentary",
        inputs={"ticker": "SPY", "lookback_days": 30},
        assertions=[
            GoldenTaskAssertion(name="schema_valid", check="schema_valid"),
            GoldenTaskAssertion(name="cost_under_50c", check="cost_under", threshold=0.50),
        ],
        description="Portfolio commentary with stress-test context.",
    ),
    GoldenTask(
        id="risk_drilldown_breach",
        name="Risk Drill-Down with Breach",
        workflow="risk_drilldown",
        inputs={"ticker": "GME", "lookback_days": 7},
        assertions=[
            GoldenTaskAssertion(name="schema_valid", check="schema_valid"),
            GoldenTaskAssertion(name="cost_under_30c", check="cost_under", threshold=0.30),
        ],
        description="Risk drill-down that should trigger HITL on breach.",
    ),
]


@dataclass(slots=True)
class GoldenTaskResult:
    """Result of running a single golden task."""

    task_id: str
    passed: bool = True
    assertions_passed: int = 0
    assertions_failed: int = 0
    failures: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    output: dict[str, Any] | None = None


def evaluate_golden_task(
    task: GoldenTask,
    run_result: dict[str, Any],
) -> GoldenTaskResult:
    """Evaluate a golden task against its assertions.

    Args:
        task: The golden task definition.
        run_result: The workflow run result from the orchestrator.

    Returns:
        GoldenTaskResult with pass/fail details.
    """
    result = GoldenTaskResult(
        task_id=task.id,
        cost_usd=run_result.get("cost_usd", 0.0),
        duration_ms=run_result.get("duration_ms", 0.0),
        output=run_result.get("output"),
    )

    for assertion in task.assertions:
        passed = _check_assertion(assertion, run_result)
        if passed:
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.failures.append(f"{assertion.name}: FAILED ({assertion.check})")

    result.passed = result.assertions_failed == 0
    return result


def _check_assertion(assertion: GoldenTaskAssertion, run_result: dict[str, Any]) -> bool:
    """Check a single assertion against the run result."""
    output = run_result.get("output") or {}

    if assertion.check == "schema_valid":
        return run_result.get("status") == "completed" and output is not None

    if assertion.check == "has_citations":
        # Check if any findings have citations
        research = output.get("research", {})
        findings = research.get("findings", [])
        return any(f.get("citations") for f in findings if isinstance(f, dict))

    if assertion.check == "cost_under":
        threshold = float(assertion.threshold) if assertion.threshold else 1.0
        return run_result.get("cost_usd", 0.0) <= threshold

    if assertion.check == "latency_under":
        threshold = float(assertion.threshold) if assertion.threshold else 60000
        return run_result.get("duration_ms", 0.0) <= threshold

    if assertion.check == "field_present":
        path = str(assertion.threshold).split(".")
        current = output
        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return False
        return current is not None

    if assertion.check == "min_count":
        # Check findings count
        research = output.get("research", {})
        findings = research.get("findings", [])
        threshold = int(assertion.threshold) if assertion.threshold else 1
        return len(findings) >= threshold

    if assertion.check == "hitl_triggered":
        return run_result.get("hitl_required", False) is True

    return True  # Unknown check type passes by default
