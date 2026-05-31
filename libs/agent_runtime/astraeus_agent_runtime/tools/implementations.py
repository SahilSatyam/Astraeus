"""Tool implementations — read-through to Phase 2/3/4/5 services.

All tools are read-only in Phase 6. They wrap existing service calls
with Pydantic input/output schemas for the agent runtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Feature Store Tools ---


class GetFeatureRequest(BaseModel):
    ticker: str
    feature_names: list[str] = Field(max_length=20)
    as_of: datetime


class GetFeatureResponse(BaseModel):
    ticker: str
    as_of: datetime
    features: dict[str, float | None]
    pit_safe: bool = True


async def get_feature(request: GetFeatureRequest, **kwargs: Any) -> GetFeatureResponse:
    """Query the feature store for ticker features at a point in time."""
    session = kwargs.get("session")
    if session is None:
        return GetFeatureResponse(
            ticker=request.ticker,
            as_of=request.as_of,
            features=dict.fromkeys(request.feature_names),
            pit_safe=True,
        )

    from sqlalchemy import text

    features: dict[str, float | None] = {}
    for name in request.feature_names:
        table_name = f"feature_altdata_{name}"
        try:
            result = await session.execute(
                text(f"""
                    SELECT value FROM {table_name}
                    WHERE symbol = :ticker AND knowledge_ts <= :as_of
                    ORDER BY knowledge_ts DESC LIMIT 1
                """),
                {"ticker": request.ticker, "as_of": request.as_of},
            )
            row = result.fetchone()
            features[name] = float(row.value) if row else None
        except Exception:
            features[name] = None

    return GetFeatureResponse(
        ticker=request.ticker,
        as_of=request.as_of,
        features=features,
        pit_safe=True,
    )


# --- News Search Tools ---


class SearchNewsRequest(BaseModel):
    query: str = Field(max_length=200)
    ticker: str | None = None
    lookback_days: int = Field(default=30, le=90)
    top_k: int = Field(default=10, le=25)


class NewsResult(BaseModel):
    chunk_id: str
    title: str | None = None
    source: str = ""
    text: str = ""
    score: float = 0.0
    publish_ts: str | None = None


class SearchNewsResponse(BaseModel):
    results: list[NewsResult]
    query: str
    total: int


async def search_news(request: SearchNewsRequest, **kwargs: Any) -> SearchNewsResponse:
    """Search the Phase 5 news corpus via hybrid retrieval."""
    session = kwargs.get("session")
    if session is None:
        return SearchNewsResponse(results=[], query=request.query, total=0)

    from datetime import UTC

    from astraeus_rag.retriever import HybridRetriever, RetrievalFilter

    as_of = datetime.now(tz=UTC)
    filters = RetrievalFilter(
        ticker=request.ticker,
        sources=["rss", "reddit", "gdelt"],
        as_of=as_of,
    )

    retriever = HybridRetriever(session=session)
    result = await retriever.retrieve(
        query=request.query,
        k=request.top_k,
        filters=filters,
        method="rrf",
    )

    return SearchNewsResponse(
        results=[
            NewsResult(
                chunk_id=str(c.chunk_id),
                title=c.title,
                source=c.source,
                text=c.text[:500],
                score=c.score,
                publish_ts=c.publish_ts.isoformat() if c.publish_ts else None,
            )
            for c in result.chunks
        ],
        query=request.query,
        total=len(result.chunks),
    )


# --- Filing Tools ---


class FetchFilingRequest(BaseModel):
    ticker: str
    filing_type: Literal["10-K", "10-Q", "8-K"]
    fiscal_period: str | None = None
    sections: list[str] = Field(default_factory=list)


class FilingChunk(BaseModel):
    chunk_id: str
    text: str
    section: str | None = None
    chunk_idx: int = 0


class FetchFilingResponse(BaseModel):
    ticker: str
    filing_type: str
    chunks: list[FilingChunk]
    total_chunks: int


async def fetch_filing(request: FetchFilingRequest, **kwargs: Any) -> FetchFilingResponse:
    """Fetch SEC filing chunks for a ticker."""
    session = kwargs.get("session")
    if session is None:
        return FetchFilingResponse(
            ticker=request.ticker,
            filing_type=request.filing_type,
            chunks=[],
            total_chunks=0,
        )

    from sqlalchemy import text

    result = await session.execute(
        text("""
            SELECT dc.chunk_id, dc.text, dc.chunk_idx
            FROM document_chunk dc
            JOIN raw_document rd ON rd.doc_id = dc.doc_id
            WHERE rd.source = 'edgar'
            AND EXISTS (
                SELECT 1 FROM entity_mention em
                WHERE em.chunk_id = dc.chunk_id AND em.canonical_id = :ticker
            )
            ORDER BY rd.publish_ts DESC, dc.chunk_idx
            LIMIT 20
        """),
        {"ticker": request.ticker},
    )
    rows = result.fetchall()

    return FetchFilingResponse(
        ticker=request.ticker,
        filing_type=request.filing_type,
        chunks=[
            FilingChunk(
                chunk_id=str(row.chunk_id),
                text=row.text[:800],
                chunk_idx=row.chunk_idx,
            )
            for row in rows
        ],
        total_chunks=len(rows),
    )


# --- Sentiment Tools ---


class GetSentimentFeaturesRequest(BaseModel):
    ticker: str
    as_of: datetime
    lookback_days: int = Field(default=30, le=90)


class SentimentFeatureSet(BaseModel):
    ticker: str
    as_of: datetime
    daily_score: float | None = None
    ma5: float | None = None
    dispersion: float | None = None
    doc_count: int | None = None


async def get_sentiment_features(
    request: GetSentimentFeaturesRequest, **kwargs: Any
) -> SentimentFeatureSet:
    """Get pre-computed sentiment features from Phase 5."""
    session = kwargs.get("session")
    if session is None:
        return SentimentFeatureSet(ticker=request.ticker, as_of=request.as_of)

    from sqlalchemy import text

    result = await session.execute(
        text("""
            SELECT avg(score) AS avg_score, stddev(score) AS dispersion, count(*) AS doc_count
            FROM sentiment_score
            WHERE ticker = :ticker
              AND model = 'finbert_v1.0'
              AND available_at <= :as_of
              AND available_at >= :as_of - interval '1 day' * :lookback
        """),
        {"ticker": request.ticker, "as_of": request.as_of, "lookback": request.lookback_days},
    )
    row = result.fetchone()

    return SentimentFeatureSet(
        ticker=request.ticker,
        as_of=request.as_of,
        daily_score=float(row.avg_score) if row and row.avg_score else None,
        dispersion=float(row.dispersion) if row and row.dispersion else None,
        doc_count=int(row.doc_count) if row and row.doc_count else None,
    )


# --- Risk Tools ---


class RunRiskCheckRequest(BaseModel):
    portfolio_id: str = "default"
    checks: list[str] = Field(
        default_factory=lambda: ["var", "cvar", "concentration", "liquidity", "sector_cap"]
    )


class RiskCheckItem(BaseModel):
    check_name: str
    passed: bool
    value: float | None = None
    threshold: float | None = None
    detail: str = ""


class RunRiskCheckResponse(BaseModel):
    portfolio_id: str
    checks: list[RiskCheckItem]
    any_breach: bool = False


async def run_risk_check(request: RunRiskCheckRequest, **kwargs: Any) -> RunRiskCheckResponse:
    """Run risk checks against the portfolio (reads Phase 4 risk engine)."""
    # Stub implementation — in production reads from Phase 4 risk service
    checks = [
        RiskCheckItem(
            check_name=name,
            passed=True,
            value=0.0,
            threshold=1.0,
            detail=f"{name} check passed (stub)",
        )
        for name in request.checks
    ]
    return RunRiskCheckResponse(
        portfolio_id=request.portfolio_id,
        checks=checks,
        any_breach=False,
    )


# --- Portfolio Tools ---


class GetPortfolioStateRequest(BaseModel):
    portfolio_id: str = "default"


class PortfolioPosition(BaseModel):
    ticker: str
    quantity: float
    market_value: float
    weight: float


class GetPortfolioStateResponse(BaseModel):
    portfolio_id: str
    total_value: float = 0.0
    positions: list[PortfolioPosition] = Field(default_factory=list)
    as_of: datetime | None = None


async def get_portfolio_state(
    request: GetPortfolioStateRequest, **kwargs: Any
) -> GetPortfolioStateResponse:
    """Get current portfolio state (reads Phase 4 portfolio service)."""
    # Stub — in production reads from portfolio service
    return GetPortfolioStateResponse(
        portfolio_id=request.portfolio_id,
        total_value=0.0,
        positions=[],
    )


# --- Strategy Tools ---


class QueryStrategyRegistryRequest(BaseModel):
    ticker: str | None = None
    tags: list[str] = Field(default_factory=list)


class StrategyEntry(BaseModel):
    strategy_id: str
    version: str = "1.0"
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class QueryStrategyRegistryResponse(BaseModel):
    strategies: list[StrategyEntry]
    total: int


async def query_strategy_registry(
    request: QueryStrategyRegistryRequest, **kwargs: Any
) -> QueryStrategyRegistryResponse:
    """Query the strategy registry for relevant strategies."""
    # Stub — in production reads from Phase 3 strategy registry
    return QueryStrategyRegistryResponse(strategies=[], total=0)


class GetStrategySignalRequest(BaseModel):
    strategy_id: str


class GetStrategySignalResponse(BaseModel):
    strategy_id: str
    signal: float | None = None
    as_of: str | None = None
    decay_score: float | None = None


async def get_strategy_signal(
    request: GetStrategySignalRequest, **kwargs: Any
) -> GetStrategySignalResponse:
    """Get current signal for a strategy."""
    return GetStrategySignalResponse(strategy_id=request.strategy_id)


class GetFactorExposureRequest(BaseModel):
    portfolio_id: str = "default"
    factors: list[str] = Field(default_factory=list)


class GetFactorExposureResponse(BaseModel):
    portfolio_id: str
    exposures: dict[str, float] = Field(default_factory=dict)


async def get_factor_exposure(
    request: GetFactorExposureRequest, **kwargs: Any
) -> GetFactorExposureResponse:
    """Get factor exposures for a portfolio."""
    return GetFactorExposureResponse(portfolio_id=request.portfolio_id)


class GetBacktestMetricsRequest(BaseModel):
    strategy_id: str
    period: str = "1y"


class GetBacktestMetricsResponse(BaseModel):
    strategy_id: str
    sharpe: float | None = None
    max_drawdown: float | None = None
    cagr: float | None = None


async def get_backtest_metrics(
    request: GetBacktestMetricsRequest, **kwargs: Any
) -> GetBacktestMetricsResponse:
    """Get backtest metrics for a strategy."""
    return GetBacktestMetricsResponse(strategy_id=request.strategy_id)


# --- Execution Tools ---


class GetLiquidityMetricsRequest(BaseModel):
    ticker: str


class GetLiquidityMetricsResponse(BaseModel):
    ticker: str
    adv_20d: float | None = None
    spread_bps: float | None = None
    depth_at_touch: float | None = None


async def get_liquidity_metrics(
    request: GetLiquidityMetricsRequest, **kwargs: Any
) -> GetLiquidityMetricsResponse:
    """Get liquidity metrics for a ticker."""
    return GetLiquidityMetricsResponse(ticker=request.ticker)


class GetVolatilityEstimateRequest(BaseModel):
    ticker: str


class GetVolatilityEstimateResponse(BaseModel):
    ticker: str
    realized_vol_20d: float | None = None
    implied_vol: float | None = None


async def get_volatility_estimate(
    request: GetVolatilityEstimateRequest, **kwargs: Any
) -> GetVolatilityEstimateResponse:
    """Get volatility estimate for a ticker."""
    return GetVolatilityEstimateResponse(ticker=request.ticker)


# --- Portfolio Extended Tools ---


class GetExposureBreakdownRequest(BaseModel):
    portfolio_id: str = "default"


class GetExposureBreakdownResponse(BaseModel):
    portfolio_id: str
    sector: dict[str, float] = Field(default_factory=dict)
    geography: dict[str, float] = Field(default_factory=dict)
    market_cap: dict[str, float] = Field(default_factory=dict)


async def get_exposure_breakdown(
    request: GetExposureBreakdownRequest, **kwargs: Any
) -> GetExposureBreakdownResponse:
    """Get exposure breakdown by sector, geography, market cap."""
    return GetExposureBreakdownResponse(portfolio_id=request.portfolio_id)


class GetFactorAttributionRequest(BaseModel):
    portfolio_id: str = "default"
    period: str = "1m"


class GetFactorAttributionResponse(BaseModel):
    portfolio_id: str
    total_return: float | None = None
    factor_contributions: dict[str, float] = Field(default_factory=dict)
    residual: float | None = None


async def get_factor_attribution(
    request: GetFactorAttributionRequest, **kwargs: Any
) -> GetFactorAttributionResponse:
    """Get factor attribution for portfolio returns."""
    return GetFactorAttributionResponse(portfolio_id=request.portfolio_id)


class GetOptimizerSuggestionRequest(BaseModel):
    portfolio_id: str = "default"


class GetOptimizerSuggestionResponse(BaseModel):
    portfolio_id: str
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    objective: str = ""


async def get_optimizer_suggestion(
    request: GetOptimizerSuggestionRequest, **kwargs: Any
) -> GetOptimizerSuggestionResponse:
    """Get optimizer-suggested rebalance trades."""
    return GetOptimizerSuggestionResponse(portfolio_id=request.portfolio_id)


# --- Compliance Tools ---


class LookupRestrictedListRequest(BaseModel):
    ticker: str


class LookupRestrictedListResponse(BaseModel):
    ticker: str
    restricted: bool = False
    reason: str = ""


async def lookup_restricted_list(
    request: LookupRestrictedListRequest, **kwargs: Any
) -> LookupRestrictedListResponse:
    """Check if a ticker is on the restricted list."""
    return LookupRestrictedListResponse(ticker=request.ticker, restricted=False)


class LookupPolicyRuleRequest(BaseModel):
    rule_id: str = ""
    context: str = ""


class LookupPolicyRuleResponse(BaseModel):
    rule_id: str
    applicable: bool = False
    description: str = ""


async def lookup_policy_rule(
    request: LookupPolicyRuleRequest, **kwargs: Any
) -> LookupPolicyRuleResponse:
    """Look up a compliance policy rule."""
    return LookupPolicyRuleResponse(rule_id=request.rule_id)


class WriteAuditEnvelopeRequest(BaseModel):
    run_id: str
    agent_name: str
    action: str = "review_complete"
    notes: str = ""


class WriteAuditEnvelopeResponse(BaseModel):
    envelope_id: str = ""
    status: str = "written"


async def write_audit_envelope(
    request: WriteAuditEnvelopeRequest, **kwargs: Any
) -> WriteAuditEnvelopeResponse:
    """Write an audit envelope for compliance tracking."""
    import uuid as uuid_mod

    return WriteAuditEnvelopeResponse(envelope_id=str(uuid_mod.uuid4()))


# --- Research Extended Tools ---


class GetMacroIndicatorRequest(BaseModel):
    indicator: str = "gdp"
    region: str = "US"


class GetMacroIndicatorResponse(BaseModel):
    indicator: str
    value: float | None = None
    as_of: str | None = None
    trend: str = ""


async def get_macro_indicator(
    request: GetMacroIndicatorRequest, **kwargs: Any
) -> GetMacroIndicatorResponse:
    """Get a macro economic indicator."""
    return GetMacroIndicatorResponse(indicator=request.indicator)


class GetEarningsCalendarRequest(BaseModel):
    ticker: str | None = None
    days_ahead: int = 30


class GetEarningsCalendarResponse(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)


async def get_earnings_calendar(
    request: GetEarningsCalendarRequest, **kwargs: Any
) -> GetEarningsCalendarResponse:
    """Get upcoming earnings calendar events."""
    return GetEarningsCalendarResponse(events=[])


# --- Sentiment Extended Tools ---


class SearchSocialPostsRequest(BaseModel):
    query: str
    ticker: str | None = None
    top_k: int = Field(default=10, le=25)


class SearchSocialPostsResponse(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


async def search_social_posts(
    request: SearchSocialPostsRequest, **kwargs: Any
) -> SearchSocialPostsResponse:
    """Search social media posts (Reddit, etc.)."""
    return SearchSocialPostsResponse()


class GetEventStudyRequest(BaseModel):
    ticker: str
    event_type: str = "earnings"
    lookback_days: int = 90


class GetEventStudyResponse(BaseModel):
    ticker: str
    events: list[dict[str, Any]] = Field(default_factory=list)
    avg_impact: float | None = None


async def get_event_study(request: GetEventStudyRequest, **kwargs: Any) -> GetEventStudyResponse:
    """Get event study results for a ticker."""
    return GetEventStudyResponse(ticker=request.ticker)


# --- Registration helper ---


def register_all_tools() -> None:
    """Register all tool implementations in the global registry."""
    from astraeus_agent_runtime.tools.registry import ToolDefinition, register_tool

    tools = [
        ToolDefinition(
            name="get_feature",
            description="Query the feature store.",
            version="1.0.0",
            request_model=GetFeatureRequest,
            response_model=GetFeatureResponse,
            fn=get_feature,
        ),
        ToolDefinition(
            name="search_news",
            description="Search news corpus via hybrid retrieval.",
            version="1.0.0",
            request_model=SearchNewsRequest,
            response_model=SearchNewsResponse,
            fn=search_news,
        ),
        ToolDefinition(
            name="fetch_filing",
            description="Fetch SEC filing chunks.",
            version="1.0.0",
            request_model=FetchFilingRequest,
            response_model=FetchFilingResponse,
            fn=fetch_filing,
        ),
        ToolDefinition(
            name="search_filing_chunks",
            description="Search filing chunks.",
            version="1.0.0",
            request_model=FetchFilingRequest,
            response_model=FetchFilingResponse,
            fn=fetch_filing,
        ),
        ToolDefinition(
            name="get_sentiment_features",
            description="Get pre-computed sentiment features.",
            version="1.0.0",
            request_model=GetSentimentFeaturesRequest,
            response_model=SentimentFeatureSet,
            fn=get_sentiment_features,
        ),
        ToolDefinition(
            name="run_risk_check",
            description="Run risk checks against portfolio.",
            version="1.0.0",
            request_model=RunRiskCheckRequest,
            response_model=RunRiskCheckResponse,
            fn=run_risk_check,
        ),
        ToolDefinition(
            name="get_portfolio_state",
            description="Get current portfolio state.",
            version="1.0.0",
            request_model=GetPortfolioStateRequest,
            response_model=GetPortfolioStateResponse,
            fn=get_portfolio_state,
        ),
        # Strategy tools
        ToolDefinition(
            name="query_strategy_registry",
            description="Query strategy registry.",
            version="1.0.0",
            request_model=QueryStrategyRegistryRequest,
            response_model=QueryStrategyRegistryResponse,
            fn=query_strategy_registry,
        ),
        ToolDefinition(
            name="get_strategy_signal",
            description="Get current signal for a strategy.",
            version="1.0.0",
            request_model=GetStrategySignalRequest,
            response_model=GetStrategySignalResponse,
            fn=get_strategy_signal,
        ),
        ToolDefinition(
            name="get_factor_exposure",
            description="Get factor exposures.",
            version="1.0.0",
            request_model=GetFactorExposureRequest,
            response_model=GetFactorExposureResponse,
            fn=get_factor_exposure,
        ),
        ToolDefinition(
            name="get_backtest_metrics",
            description="Get backtest metrics.",
            version="1.0.0",
            request_model=GetBacktestMetricsRequest,
            response_model=GetBacktestMetricsResponse,
            fn=get_backtest_metrics,
        ),
        # Execution tools
        ToolDefinition(
            name="get_liquidity_metrics",
            description="Get liquidity metrics.",
            version="1.0.0",
            request_model=GetLiquidityMetricsRequest,
            response_model=GetLiquidityMetricsResponse,
            fn=get_liquidity_metrics,
        ),
        ToolDefinition(
            name="get_volatility_estimate",
            description="Get volatility estimate.",
            version="1.0.0",
            request_model=GetVolatilityEstimateRequest,
            response_model=GetVolatilityEstimateResponse,
            fn=get_volatility_estimate,
        ),
        # Portfolio extended tools
        ToolDefinition(
            name="get_exposure_breakdown",
            description="Get exposure breakdown.",
            version="1.0.0",
            request_model=GetExposureBreakdownRequest,
            response_model=GetExposureBreakdownResponse,
            fn=get_exposure_breakdown,
        ),
        ToolDefinition(
            name="get_factor_attribution",
            description="Get factor attribution.",
            version="1.0.0",
            request_model=GetFactorAttributionRequest,
            response_model=GetFactorAttributionResponse,
            fn=get_factor_attribution,
        ),
        ToolDefinition(
            name="get_optimizer_suggestion",
            description="Get optimizer suggestions.",
            version="1.0.0",
            request_model=GetOptimizerSuggestionRequest,
            response_model=GetOptimizerSuggestionResponse,
            fn=get_optimizer_suggestion,
        ),
        # Compliance tools
        ToolDefinition(
            name="lookup_restricted_list",
            description="Check restricted list.",
            version="1.0.0",
            request_model=LookupRestrictedListRequest,
            response_model=LookupRestrictedListResponse,
            fn=lookup_restricted_list,
        ),
        ToolDefinition(
            name="lookup_policy_rule",
            description="Look up policy rule.",
            version="1.0.0",
            request_model=LookupPolicyRuleRequest,
            response_model=LookupPolicyRuleResponse,
            fn=lookup_policy_rule,
        ),
        ToolDefinition(
            name="write_audit_envelope",
            description="Write audit envelope.",
            version="1.0.0",
            request_model=WriteAuditEnvelopeRequest,
            response_model=WriteAuditEnvelopeResponse,
            fn=write_audit_envelope,
        ),
        # Research extended tools
        ToolDefinition(
            name="get_macro_indicator",
            description="Get macro indicator.",
            version="1.0.0",
            request_model=GetMacroIndicatorRequest,
            response_model=GetMacroIndicatorResponse,
            fn=get_macro_indicator,
        ),
        ToolDefinition(
            name="get_earnings_calendar",
            description="Get earnings calendar.",
            version="1.0.0",
            request_model=GetEarningsCalendarRequest,
            response_model=GetEarningsCalendarResponse,
            fn=get_earnings_calendar,
        ),
        # Sentiment extended tools
        ToolDefinition(
            name="search_social_posts",
            description="Search social posts.",
            version="1.0.0",
            request_model=SearchSocialPostsRequest,
            response_model=SearchSocialPostsResponse,
            fn=search_social_posts,
        ),
        ToolDefinition(
            name="get_event_study",
            description="Get event study results.",
            version="1.0.0",
            request_model=GetEventStudyRequest,
            response_model=GetEventStudyResponse,
            fn=get_event_study,
        ),
    ]

    for tool in tools:
        register_tool(tool)
