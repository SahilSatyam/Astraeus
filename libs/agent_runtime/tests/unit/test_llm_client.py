"""Unit tests for the LLM client wrapper."""

from __future__ import annotations

from astraeus_agent_runtime.llm_client import (
    MODEL_ROUTING,
    LLMCallRecord,
    LLMClient,
    LLMResponse,
    compute_cost,
)


class TestCostComputation:
    """Test cost calculation logic."""

    def test_known_model_cost(self) -> None:
        cost = compute_cost(
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
        )
        # 1000 * 3.0/1M + 500 * 15.0/1M = 0.003 + 0.0075 = 0.0105
        assert abs(cost - 0.0105) < 0.0001

    def test_cache_reduces_cost(self) -> None:
        cost_no_cache = compute_cost(
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
        )
        cost_with_cache = compute_cost(
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=800,
        )
        # Cache read is cheaper than regular input
        assert cost_with_cache < cost_no_cache

    def test_unknown_model_fallback(self) -> None:
        cost = compute_cost(
            model="unknown-model-v99",
            input_tokens=1000,
            output_tokens=500,
        )
        # Should use conservative estimate
        assert cost > 0

    def test_zero_tokens_zero_cost(self) -> None:
        cost = compute_cost(
            model="claude-sonnet-4-20250514",
            input_tokens=0,
            output_tokens=0,
        )
        assert cost == 0.0


class TestModelRouting:
    """Test model routing configuration."""

    def test_routing_tiers_defined(self) -> None:
        assert "reasoning" in MODEL_ROUTING
        assert "synthesis" in MODEL_ROUTING
        assert "classification" in MODEL_ROUTING
        assert "cheap" in MODEL_ROUTING

    def test_reasoning_uses_sonnet(self) -> None:
        assert "sonnet" in MODEL_ROUTING["reasoning"]

    def test_classification_uses_haiku(self) -> None:
        assert "haiku" in MODEL_ROUTING["classification"]


class TestLLMResponse:
    """Test LLMResponse dataclass."""

    def test_response_fields(self) -> None:
        resp = LLMResponse(
            content='{"ticker": "AAPL"}',
            model="claude-sonnet-4-20250514",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            latency_ms=500.0,
        )
        assert resp.content == '{"ticker": "AAPL"}'
        assert resp.model == "claude-sonnet-4-20250514"
        assert resp.cost_usd == 0.001


class TestLLMClient:
    """Test LLM client initialization."""

    def test_client_init(self) -> None:
        client = LLMClient(
            anthropic_api_key="test-key",
            default_model="claude-sonnet-4-20250514",
        )
        assert client._default_model == "claude-sonnet-4-20250514"
        assert client.call_records == []

    def test_clear_records(self) -> None:
        client = LLMClient()
        client._call_records.append(LLMCallRecord(model="test"))
        assert len(client.call_records) == 1
        client.clear_records()
        assert len(client.call_records) == 0
