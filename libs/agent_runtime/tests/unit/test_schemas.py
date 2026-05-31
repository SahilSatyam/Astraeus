"""Unit tests for agent output schemas."""

from __future__ import annotations

from datetime import UTC, datetime

from astraeus_agent_runtime.schemas import (
    Citation,
    ComplianceResult,
    ExecutionAdvice,
    ResearchFinding,
    ResearchOutput,
    RiskAssessment,
    SentimentNarrative,
    StrategyOutput,
    TradeThesisOutput,
)


class TestCitation:
    """Test Citation schema."""

    def test_valid_citation(self) -> None:
        cit = Citation(
            chunk_id="abc123",
            source_type="filing",
            source_id="0000320193-23-000106",
            span=(10, 50),
            quoted_text="Revenue grew 10% year-over-year.",
        )
        assert cit.chunk_id == "abc123"
        assert cit.source_type == "filing"

    def test_citation_json_roundtrip(self) -> None:
        cit = Citation(chunk_id="x", source_type="news", source_id="rss_123")
        data = cit.model_dump()
        restored = Citation.model_validate(data)
        assert restored.chunk_id == "x"


class TestResearchOutput:
    """Test ResearchOutput schema."""

    def test_valid_research_output(self) -> None:
        output = ResearchOutput(
            ticker="AAPL",
            as_of=datetime(2024, 12, 15, tzinfo=UTC),
            summary="Apple shows strong services growth.",
            findings=[
                ResearchFinding(
                    claim="Services revenue grew 12%",
                    citations=[Citation(chunk_id="c1", source_type="filing", source_id="s1")],
                    confidence="high",
                ),
            ],
        )
        assert output.schema_version == "v1"
        assert output.ticker == "AAPL"
        assert len(output.findings) == 1

    def test_research_output_json_schema(self) -> None:
        schema = ResearchOutput.model_json_schema()
        assert "properties" in schema
        assert "ticker" in schema["properties"]
        assert "findings" in schema["properties"]


class TestSentimentNarrative:
    """Test SentimentNarrative schema."""

    def test_valid_sentiment(self) -> None:
        output = SentimentNarrative(
            ticker="AAPL",
            as_of=datetime(2024, 12, 15, tzinfo=UTC),
            score=0.65,
            score_delta=0.12,
            caveats=["Limited social data for this period"],
        )
        assert output.score == 0.65
        assert output.schema_version == "v1"


class TestRiskAssessment:
    """Test RiskAssessment schema."""

    def test_risk_with_breach(self) -> None:
        output = RiskAssessment(
            as_of=datetime(2024, 12, 15, tzinfo=UTC),
            hitl_required=True,
            hitl_reason="VaR breach: 12% > 10% threshold",
        )
        assert output.hitl_required is True

    def test_risk_no_breach(self) -> None:
        output = RiskAssessment(
            as_of=datetime(2024, 12, 15, tzinfo=UTC),
            narrative="All checks passed.",
        )
        assert output.hitl_required is False


class TestExecutionAdvice:
    """Test ExecutionAdvice schema."""

    def test_always_requires_human(self) -> None:
        """Critical: Phase 6 execution advice always requires human execution."""
        advice = ExecutionAdvice(algo="TWAP")
        assert advice.requires_human_execution is True

    def test_valid_algos(self) -> None:
        for algo in ("TWAP", "VWAP", "IS", "POV", "MARKET"):
            advice = ExecutionAdvice(algo=algo)
            assert advice.algo == algo


class TestComplianceResult:
    """Test ComplianceResult schema."""

    def test_approved(self) -> None:
        result = ComplianceResult(approved=True)
        assert result.approved is True
        assert result.flags == []

    def test_flagged(self) -> None:
        result = ComplianceResult(
            approved=False,
            flags=["restricted_ticker", "missing_citation"],
        )
        assert result.approved is False
        assert len(result.flags) == 2


class TestTradeThesisOutput:
    """Test composite TradeThesisOutput schema."""

    def test_full_thesis(self) -> None:
        thesis = TradeThesisOutput(
            ticker="AAPL",
            as_of=datetime(2024, 12, 15, tzinfo=UTC),
            research=ResearchOutput(
                ticker="AAPL",
                as_of=datetime(2024, 12, 15, tzinfo=UTC),
                summary="Strong fundamentals.",
                findings=[
                    ResearchFinding(
                        claim="Revenue up",
                        citations=[Citation(chunk_id="c1", source_type="filing", source_id="s1")],
                        confidence="high",
                    ),
                ],
            ),
            sentiment=SentimentNarrative(
                ticker="AAPL",
                as_of=datetime(2024, 12, 15, tzinfo=UTC),
            ),
            strategy=StrategyOutput(
                ticker="AAPL",
                as_of=datetime(2024, 12, 15, tzinfo=UTC),
            ),
            risk=RiskAssessment(as_of=datetime(2024, 12, 15, tzinfo=UTC)),
            compliance=ComplianceResult(approved=True),
            contrarian_points=["Valuation stretched vs peers"],
        )
        assert thesis.ticker == "AAPL"
        assert thesis.compliance.approved is True
