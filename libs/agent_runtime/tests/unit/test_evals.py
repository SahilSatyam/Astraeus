"""Unit tests for the eval suite."""

from __future__ import annotations

from astraeus_agent_runtime.evals.faithfulness import evaluate_faithfulness
from astraeus_agent_runtime.evals.golden_tasks import (
    GOLDEN_TASKS,
    GoldenTask,
    GoldenTaskAssertion,
    evaluate_golden_task,
)
from astraeus_agent_runtime.evals.injection_battery import (
    INJECTION_INPUTS,
    run_injection_battery,
)


class TestGoldenTasks:
    """Test golden task evaluation."""

    def test_golden_tasks_defined(self) -> None:
        assert len(GOLDEN_TASKS) >= 5

    def test_aapl_thesis_task_exists(self) -> None:
        task = next((t for t in GOLDEN_TASKS if t.id == "aapl_trade_thesis"), None)
        assert task is not None
        assert task.workflow == "trade_thesis"
        assert task.inputs["ticker"] == "AAPL"

    def test_evaluate_passing_task(self) -> None:
        task = GoldenTask(
            id="test",
            name="Test",
            workflow="trade_thesis",
            inputs={"ticker": "AAPL"},
            assertions=[
                GoldenTaskAssertion(name="schema_valid", check="schema_valid"),
                GoldenTaskAssertion(name="cost_ok", check="cost_under", threshold=1.0),
            ],
        )
        run_result = {
            "status": "completed",
            "output": {"research": {"findings": []}},
            "cost_usd": 0.25,
            "duration_ms": 5000,
        }
        result = evaluate_golden_task(task, run_result)
        assert result.passed is True
        assert result.assertions_passed == 2

    def test_evaluate_failing_task(self) -> None:
        task = GoldenTask(
            id="test",
            name="Test",
            workflow="trade_thesis",
            inputs={"ticker": "AAPL"},
            assertions=[
                GoldenTaskAssertion(name="cost_ok", check="cost_under", threshold=0.10),
            ],
        )
        run_result = {"status": "completed", "output": {}, "cost_usd": 0.50}
        result = evaluate_golden_task(task, run_result)
        assert result.passed is False
        assert result.assertions_failed == 1


class TestFaithfulness:
    """Test faithfulness evaluation."""

    def test_empty_output(self) -> None:
        result = evaluate_faithfulness({})
        assert result.total_claims == 0
        assert result.passes_threshold is True

    def test_entailed_claim(self) -> None:
        output = {
            "findings": [
                {
                    "claim": "Apple revenue grew significantly in services",
                    "citations": [{"chunk_id": "c1", "quoted_text": "Apple reported significant revenue growth in services segment"}],
                }
            ]
        }
        chunk_lookup = {"c1": "Apple reported significant revenue growth in services segment reaching $20B"}
        result = evaluate_faithfulness(output, chunk_lookup)
        assert result.total_claims == 1
        assert result.entailed >= 1

    def test_no_chunk_text_neutral(self) -> None:
        output = {
            "findings": [
                {
                    "claim": "Revenue grew 10%",
                    "citations": [{"chunk_id": "missing"}],
                }
            ]
        }
        result = evaluate_faithfulness(output, chunk_lookup={})
        assert result.total_claims == 1
        assert result.neutral >= 1


class TestInjectionBattery:
    """Test the injection battery."""

    def test_battery_has_inputs(self) -> None:
        assert len(INJECTION_INPUTS) >= 50

    def test_battery_detects_most(self) -> None:
        result = run_injection_battery(detection_threshold=0.3)
        assert result.total == len(INJECTION_INPUTS)
        # Simple regex patterns detect a subset; production uses ML classifier
        # Our patterns cover: "ignore previous", "disregard prior", "you are now",
        # "system:", "forget everything", "new instructions:", "override instructions"
        assert result.detection_rate >= 0.50

    def test_battery_result_fields(self) -> None:
        result = run_injection_battery()
        assert result.total > 0
        assert result.detected + result.missed == result.total
