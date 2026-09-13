"""Integration test: synthetic Phase 3 signals → published portfolio + report.

Validates the full daily pipeline end-to-end:
1. Synthetic signals are generated for a 20-asset universe.
2. Covariance is estimated from synthetic returns.
3. All four optimizers produce feasible portfolios.
4. Risk engine computes a full risk report.
5. Risk gate produces a binary pass/fail decision.
6. Fallback is applied on rejection.
7. Attribution runs on realized returns.
8. PDF/HTML report is generated.

This test does NOT require a database or Redpanda — it uses in-memory
data structures to validate the pipeline logic.
"""

from __future__ import annotations

import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from astraeus_portfolio.attribution.runner import AttributionRunner
from astraeus_portfolio.constraints.base import Constraint
from astraeus_portfolio.constraints.box import BoxConstraint
from astraeus_portfolio.constraints.concentration import ConcentrationConstraint
from astraeus_portfolio.constraints.turnover import TurnoverConstraint
from astraeus_portfolio.contracts import (
    ClusterReport,
    ConstraintDiag,
    CovarianceMethod,
    FallbackAction,
    OptContext,
    OptimizerType,
    PortfolioStatus,
    PortfolioWeight,
    RiskReport,
    ScenarioName,
    ScenarioResult,
    TargetPortfolio,
)
from astraeus_portfolio.optimizers.black_litterman import BlackLittermanOptimizer
from astraeus_portfolio.optimizers.cvar import CVaROptimizer
from astraeus_portfolio.optimizers.fallback import FallbackConfig, FallbackExecutor
from astraeus_portfolio.optimizers.mvo import MeanVarianceOptimizer
from astraeus_portfolio.optimizers.risk_parity import RiskParityOptimizer
from astraeus_portfolio.orchestration.daily_job import (
    DailyPipelineOrchestrator,
    PipelineConfig,
)
from astraeus_portfolio.reporting.exposure import build_exposure_report
from astraeus_portfolio.reporting.pdf import DailyReportRenderer
from astraeus_portfolio.reporting.risk_report import build_risk_report_data
from astraeus_portfolio.risk.validation import (
    RiskGate,
    RiskPolicy,
    RiskPolicyThresholds,
    ValidationStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

N_ASSETS = 20
N_DAYS = 300
SYMBOLS = [f"ASSET_{i:02d}" for i in range(N_ASSETS)]
SECTORS = ["Technology", "Healthcare", "Financials", "Energy", "Consumer"]


@pytest.fixture
def rng() -> np.random.Generator:
    """Deterministic random number generator."""
    return np.random.default_rng(seed=42)


@pytest.fixture
def synthetic_returns(rng: np.random.Generator) -> np.ndarray:
    """Generate synthetic daily returns (T x N)."""
    # Correlated returns via factor model
    n_factors = 3
    factor_returns = rng.normal(0, 0.01, size=(N_DAYS, n_factors))
    loadings = rng.normal(0.5, 0.3, size=(N_ASSETS, n_factors))
    idio = rng.normal(0, 0.005, size=(N_DAYS, N_ASSETS))
    returns = factor_returns @ loadings.T + idio
    return returns


@pytest.fixture
def market_returns(rng: np.random.Generator) -> np.ndarray:
    """Synthetic SPY returns."""
    return rng.normal(0.0003, 0.01, size=N_DAYS)


@pytest.fixture
def sector_map() -> dict[str, str]:
    """Symbol to sector mapping."""
    return {SYMBOLS[i]: SECTORS[i % len(SECTORS)] for i in range(N_ASSETS)}


@pytest.fixture
def opt_context(
    synthetic_returns: np.ndarray,
    market_returns: np.ndarray,
    sector_map: dict[str, str],
    rng: np.random.Generator,
) -> OptContext:
    """Build a full OptContext from synthetic data."""
    from astraeus_portfolio.contracts import CovarianceConfig
    from astraeus_portfolio.covariance.ledoit_wolf import LedoitWolfEstimator

    estimator = LedoitWolfEstimator()
    cov_result = estimator.estimate(synthetic_returns, CovarianceConfig())

    # Expected returns from synthetic signals
    expected_returns = rng.normal(0.0005, 0.002, size=N_ASSETS)

    # Betas
    market_var = np.var(market_returns, ddof=1)
    betas = np.array(
        [
            np.cov(synthetic_returns[:, i], market_returns)[0, 1] / market_var
            for i in range(N_ASSETS)
        ]
    )

    constraints: list[Constraint] = [
        BoxConstraint(w_max=0.15),
        TurnoverConstraint(mode="hard_cap", turnover_max=0.5),
        ConcentrationConstraint(top_k=5, top_k_cap=0.50, herfindahl_max=0.10),
    ]

    return OptContext(
        strategy_id="test_momentum_daily",
        as_of_ts=datetime(2026, 5, 28, 20, 30, 0),
        n_assets=N_ASSETS,
        symbols=SYMBOLS,
        expected_returns=expected_returns,
        covariance=cov_result.matrix,
        current_weights=np.ones(N_ASSETS) / N_ASSETS,
        prices=rng.uniform(50, 500, size=N_ASSETS),
        adv=rng.uniform(500_000, 5_000_000, size=N_ASSETS),
        sector_map=sector_map,
        beta=betas,
        factor_loadings=None,
        views=None,
        scenarios=synthetic_returns[-1000:] if N_DAYS >= 1000 else synthetic_returns,
        regime_label=None,
        constraints=constraints,
        risk_aversion=5.0,
        nav=Decimal("10000.00"),
        seed=42,
    )


def _build_mock_risk_report(portfolio: TargetPortfolio) -> RiskReport:
    """Build a mock risk report that passes the gate."""
    return RiskReport(
        report_id=uuid4(),
        portfolio_id=portfolio.portfolio_id,
        as_of_ts=portfolio.as_of_ts,
        var_95_hist=Decimal("0.015"),
        var_99_hist=Decimal("0.025"),
        cvar_95_hist=Decimal("0.020"),
        cvar_99_hist=Decimal("0.035"),
        var_95_param=Decimal("0.014"),
        cvar_95_param=Decimal("0.019"),
        var_95_mc=Decimal("0.016"),
        cvar_95_mc=Decimal("0.021"),
        stress_scenarios=[
            ScenarioResult(
                scenario_name=ScenarioName.GFC_2008,
                scenario_version="v1.0",
                total_pnl_pct=Decimal("-18.5"),
                factor_contributions={"MKT": Decimal("-15.0"), "SMB": Decimal("-3.5")},
                asset_contributions={},
            ),
            ScenarioResult(
                scenario_name=ScenarioName.COVID_2020,
                scenario_version="v1.0",
                total_pnl_pct=Decimal("-20.0"),
                factor_contributions={"MKT": Decimal("-17.0"), "HML": Decimal("-3.0")},
                asset_contributions={},
            ),
            ScenarioResult(
                scenario_name=ScenarioName.RATE_SHOCK,
                scenario_version="v1.0",
                total_pnl_pct=Decimal("-10.0"),
                factor_contributions={"MKT": Decimal("-7.0"), "CMA": Decimal("-3.0")},
                asset_contributions={},
            ),
            ScenarioResult(
                scenario_name=ScenarioName.FLASH_CRASH,
                scenario_version="v1.0",
                total_pnl_pct=Decimal("-8.0"),
                factor_contributions={"MKT": Decimal("-8.0")},
                asset_contributions={},
            ),
        ],
        cluster_concentration=ClusterReport(
            n_clusters=5,
            max_cluster_weight=Decimal("0.28"),
            herfindahl_index=Decimal("0.06"),
            effective_n_bets=Decimal("12.5"),
            cluster_assignments={s: i % 5 for i, s in enumerate(SYMBOLS)},
        ),
        sector_exposure={s: Decimal("0.20") for s in SECTORS},
        factor_exposure={"MKT": Decimal("0.95"), "SMB": Decimal("0.1"), "HML": Decimal("-0.05")},
        beta=Decimal("0.05"),
        effective_n_bets=Decimal("12.5"),
        liquidity_5day_pct=Decimal("0.95"),
        constraint_diagnostics=[
            ConstraintDiag(
                constraint_name="box",
                satisfied=True,
                shadow_price=0.001,
                slack=0.05,
                diagnostic={"max_weight": 0.10},
            ),
        ],
        policy_version="v1.0",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAllOptimizersProduceFeasiblePortfolios:
    """P4-11 / Exit criteria: all four optimizers produce feasible portfolios."""

    def test_mvo_produces_feasible_portfolio(self, opt_context: OptContext) -> None:
        optimizer = MeanVarianceOptimizer()
        result = optimizer.run(opt_context)

        assert result.status in ("optimal", "optimal_inaccurate")
        assert result.weights.shape == (N_ASSETS,)
        assert abs(np.sum(result.weights) - 1.0) < 1e-4
        assert np.all(result.weights >= -1e-6)

    def test_risk_parity_produces_feasible_portfolio(self, opt_context: OptContext) -> None:
        optimizer = RiskParityOptimizer()
        result = optimizer.run(opt_context)

        assert result.status in ("optimal", "optimal_inaccurate")
        assert result.weights.shape == (N_ASSETS,)
        assert abs(np.sum(result.weights) - 1.0) < 1e-4
        assert np.all(result.weights >= -1e-6)

    def test_cvar_produces_feasible_portfolio(self, opt_context: OptContext) -> None:
        # CVaR needs scenarios (minimum 1000)
        rng = np.random.default_rng(42)
        scenarios = rng.normal(0, 0.01, size=(1200, N_ASSETS))
        ctx = opt_context.model_copy(update={"scenarios": scenarios})

        optimizer = CVaROptimizer()
        result = optimizer.run(ctx)

        assert result.status in ("optimal", "optimal_inaccurate")
        assert result.weights.shape == (N_ASSETS,)
        assert abs(np.sum(result.weights) - 1.0) < 1e-4

    def test_black_litterman_produces_feasible_portfolio(self, opt_context: OptContext) -> None:
        from astraeus_portfolio.contracts import View

        views = [
            View(
                view_id="test_view_1",
                as_of_ts=datetime(2026, 5, 28, 16, 0, 0),
                source="manual",
                P=[[1.0 if j == 0 else (-1.0 if j == 1 else 0.0) for j in range(N_ASSETS)]],
                Q=[0.02],
                confidence=[0.6],
                rationale="ASSET_00 outperforms ASSET_01 by 2%",
                expires_at=datetime(2026, 6, 28),
            )
        ]
        ctx = opt_context.model_copy(update={"views": views})

        optimizer = BlackLittermanOptimizer()
        result = optimizer.run(ctx)

        assert result.status in ("optimal", "optimal_inaccurate")
        assert result.weights.shape == (N_ASSETS,)
        assert abs(np.sum(result.weights) - 1.0) < 1e-4


class TestRiskGateIntegration:
    """Exit criteria: gate determinism — passing always passes, failing always rejects."""

    def test_passing_portfolio_passes_gate(self, opt_context: OptContext) -> None:
        optimizer = MeanVarianceOptimizer()
        result = optimizer.run(opt_context)

        weights = [
            PortfolioWeight(symbol=SYMBOLS[i], weight=Decimal(str(round(result.weights[i], 8))))
            for i in range(N_ASSETS)
            if abs(result.weights[i]) > 1e-8
        ]

        portfolio = TargetPortfolio(
            portfolio_id=uuid4(),
            strategy_id="test_strategy",
            as_of_ts=opt_context.as_of_ts,
            nav_currency="USD",
            nav=Decimal("10000"),
            weights=weights,
            status=PortfolioStatus.PASSED,
            optimizer=OptimizerType.MVO,
            optimizer_config_hash="test",
            constraint_set_hash="test",
            covariance_estimator=CovarianceMethod.LEDOIT_WOLF,
            expected_return_source="synthetic",
            risk_report_id=uuid4(),
            created_at=datetime.utcnow(),
        )

        risk_report = _build_mock_risk_report(portfolio)

        # Use a lenient policy that matches the box constraint (w_max=0.15)
        gate = RiskGate()
        policy = RiskPolicy(
            policy_version="v1.0",
            thresholds=RiskPolicyThresholds(single_name_max=0.16),
        )

        validation = gate.validate(portfolio, risk_report, policy)
        assert validation.status == ValidationStatus.PASSED
        assert len(validation.failed_checks) == 0

    def test_failing_portfolio_is_rejected(self) -> None:
        """Portfolio with excessive CVaR is rejected."""
        portfolio = TargetPortfolio(
            portfolio_id=uuid4(),
            strategy_id="test_strategy",
            as_of_ts=datetime(2026, 5, 28, 20, 30),
            nav_currency="USD",
            nav=Decimal("10000"),
            weights=[PortfolioWeight(symbol="AAPL", weight=Decimal("1.0"))],
            status=PortfolioStatus.PASSED,
            optimizer=OptimizerType.MVO,
            optimizer_config_hash="test",
            constraint_set_hash="test",
            covariance_estimator=CovarianceMethod.LEDOIT_WOLF,
            expected_return_source="synthetic",
            risk_report_id=uuid4(),
            created_at=datetime.utcnow(),
        )

        # Risk report with excessive CVaR
        risk_report = RiskReport(
            report_id=uuid4(),
            portfolio_id=portfolio.portfolio_id,
            as_of_ts=portfolio.as_of_ts,
            var_95_hist=Decimal("0.08"),
            var_99_hist=Decimal("0.12"),
            cvar_95_hist=Decimal("0.10"),  # Exceeds 3% threshold
            cvar_99_hist=Decimal("0.15"),  # Exceeds 5% threshold
            var_95_param=Decimal("0.07"),
            cvar_95_param=Decimal("0.09"),
            var_95_mc=Decimal("0.08"),
            cvar_95_mc=Decimal("0.10"),
            stress_scenarios=[
                ScenarioResult(
                    scenario_name=ScenarioName.GFC_2008,
                    scenario_version="v1.0",
                    total_pnl_pct=Decimal("-40.0"),  # Exceeds -25% threshold
                    factor_contributions={},
                    asset_contributions={},
                ),
                ScenarioResult(
                    scenario_name=ScenarioName.COVID_2020,
                    scenario_version="v1.0",
                    total_pnl_pct=Decimal("-20.0"),
                    factor_contributions={},
                    asset_contributions={},
                ),
                ScenarioResult(
                    scenario_name=ScenarioName.RATE_SHOCK,
                    scenario_version="v1.0",
                    total_pnl_pct=Decimal("-10.0"),
                    factor_contributions={},
                    asset_contributions={},
                ),
                ScenarioResult(
                    scenario_name=ScenarioName.FLASH_CRASH,
                    scenario_version="v1.0",
                    total_pnl_pct=Decimal("-8.0"),
                    factor_contributions={},
                    asset_contributions={},
                ),
            ],
            cluster_concentration=ClusterReport(
                n_clusters=1,
                max_cluster_weight=Decimal("1.0"),
                herfindahl_index=Decimal("1.0"),
                effective_n_bets=Decimal("1.0"),
                cluster_assignments={"AAPL": 0},
            ),
            sector_exposure={"Technology": Decimal("1.0")},
            factor_exposure={"MKT": Decimal("1.2")},
            beta=Decimal("1.2"),
            effective_n_bets=Decimal("1.0"),
            liquidity_5day_pct=Decimal("0.95"),
            constraint_diagnostics=[],
            policy_version="v1.0",
        )

        gate = RiskGate()
        policy = RiskPolicy(policy_version="v1.0")

        validation = gate.validate(portfolio, risk_report, policy)
        assert validation.status == ValidationStatus.REJECTED
        assert len(validation.failed_checks) > 0


class TestFallbackExecution:
    """Exit criteria: rejection triggers configured fallback action."""

    def test_cash_fallback(self) -> None:
        executor = FallbackExecutor()
        config = FallbackConfig(action=FallbackAction.CASH)

        outcome = executor.execute(
            config=config,
            strategy_id="test_strategy",
            as_of_ts=datetime(2026, 5, 28, 20, 30),
            nav=Decimal("10000"),
            prior_portfolio=None,
        )

        assert outcome.action_taken == FallbackAction.CASH
        assert outcome.portfolio is not None
        assert outcome.portfolio.status == PortfolioStatus.FALLBACK_APPLIED
        assert outcome.portfolio.weights[0].symbol == "CASH"

    def test_hold_prior_fallback(self, opt_context: OptContext) -> None:
        # Create a prior portfolio
        prior = TargetPortfolio(
            portfolio_id=uuid4(),
            strategy_id="test_strategy",
            as_of_ts=datetime(2026, 5, 27, 20, 30),
            nav_currency="USD",
            nav=Decimal("10000"),
            weights=[
                PortfolioWeight(symbol="ASSET_00", weight=Decimal("0.5")),
                PortfolioWeight(symbol="ASSET_01", weight=Decimal("0.5")),
            ],
            status=PortfolioStatus.PASSED,
            optimizer=OptimizerType.MVO,
            optimizer_config_hash="test",
            constraint_set_hash="test",
            covariance_estimator=CovarianceMethod.LEDOIT_WOLF,
            expected_return_source="synthetic",
            risk_report_id=uuid4(),
            created_at=datetime.utcnow(),
        )

        executor = FallbackExecutor()
        config = FallbackConfig(action=FallbackAction.HOLD_PRIOR)

        outcome = executor.execute(
            config=config,
            strategy_id="test_strategy",
            as_of_ts=datetime(2026, 5, 28, 20, 30),
            nav=Decimal("10000"),
            prior_portfolio=prior,
        )

        assert outcome.action_taken == FallbackAction.HOLD_PRIOR
        assert outcome.portfolio is not None
        assert outcome.portfolio.parent_portfolio_id == prior.portfolio_id
        assert len(outcome.portfolio.weights) == 2


class TestDailyPipelineEndToEnd:
    """Exit criteria: daily job produces target portfolio with full risk report."""

    def test_pipeline_completes_with_synthetic_data(
        self,
        synthetic_returns: np.ndarray,
        market_returns: np.ndarray,
        sector_map: dict[str, str],
        rng: np.random.Generator,
    ) -> None:
        config = PipelineConfig(
            strategy_id="test_momentum_daily",
            optimizer_type=OptimizerType.MVO,
            covariance_method=CovarianceMethod.LEDOIT_WOLF,
            nav=Decimal("10000.00"),
        )

        orchestrator = DailyPipelineOrchestrator(config)
        result = orchestrator.run(
            as_of_date=date(2026, 5, 28),
            returns_matrix=synthetic_returns,
            market_returns=market_returns,
            symbols=SYMBOLS,
            expected_returns=rng.normal(0.0005, 0.002, size=N_ASSETS),
            prices=rng.uniform(50, 500, size=N_ASSETS),
            adv=rng.uniform(500_000, 5_000_000, size=N_ASSETS),
            sector_map=sector_map,
            constraints=[
                BoxConstraint(w_max=0.15),
                TurnoverConstraint(mode="hard_cap", turnover_max=0.5),
            ],
        )

        assert result.status == "completed"
        assert result.portfolio is not None
        assert len(result.portfolio.weights) > 0
        assert result.total_duration_ms > 0

    def test_pipeline_idempotency(
        self,
        synthetic_returns: np.ndarray,
        market_returns: np.ndarray,
        sector_map: dict[str, str],
        rng: np.random.Generator,
    ) -> None:
        """Running pipeline twice produces same result."""
        config = PipelineConfig(
            strategy_id="test_momentum_daily",
            optimizer_type=OptimizerType.MVO,
            nav=Decimal("10000.00"),
        )

        expected_returns = rng.normal(0.0005, 0.002, size=N_ASSETS)
        prices = rng.uniform(50, 500, size=N_ASSETS)
        adv = rng.uniform(500_000, 5_000_000, size=N_ASSETS)

        orchestrator = DailyPipelineOrchestrator(config)
        kwargs = {
            "as_of_date": date(2026, 5, 28),
            "returns_matrix": synthetic_returns,
            "market_returns": market_returns,
            "symbols": SYMBOLS,
            "expected_returns": expected_returns,
            "prices": prices,
            "adv": adv,
            "sector_map": sector_map,
            "constraints": [BoxConstraint(w_max=0.15)],
        }

        result1 = orchestrator.run(**kwargs)
        result2 = orchestrator.run(**kwargs)

        assert result1.status == result2.status == "completed"
        # Weights should be identical (deterministic)
        w1 = {pw.symbol: pw.weight for pw in result1.portfolio.weights}
        w2 = {pw.symbol: pw.weight for pw in result2.portfolio.weights}
        assert w1 == w2


class TestAttributionIntegration:
    """Exit criteria: attribution runs T+1 with non-trivial factor and idio PnL."""

    def test_factor_attribution_produces_results(
        self,
        synthetic_returns: np.ndarray,
        rng: np.random.Generator,
    ) -> None:
        runner = AttributionRunner()

        # Simulate portfolio weights and realized returns
        portfolio_weights = {SYMBOLS[i]: 1.0 / N_ASSETS for i in range(N_ASSETS)}
        asset_returns = {SYMBOLS[i]: float(synthetic_returns[-1, i]) for i in range(N_ASSETS)}

        # Factor returns (FF5 + MOM)
        factor_names = ["MKT-RF", "SMB", "HML", "RMW", "CMA", "MOM"]
        factor_returns = {f: float(rng.normal(0, 0.005)) for f in factor_names}

        # Historical factor returns for regression
        factor_return_history = rng.normal(0, 0.005, size=(N_DAYS, len(factor_names)))

        results = runner.run_full_attribution(
            portfolio_id=uuid4(),
            as_of_date=date(2026, 5, 29),
            portfolio_weights=portfolio_weights,
            asset_returns=asset_returns,
            factor_returns=factor_returns,
            asset_return_history=synthetic_returns,
            factor_return_history=factor_return_history,
        )

        assert len(results) >= 1
        factor_result = results[0]
        assert factor_result.method == "factor_ff5_mom"
        assert factor_result.factor_pnl is not None
        assert len(factor_result.factor_pnl) == 6
        assert factor_result.idio_pnl_bps is not None


class TestReportGeneration:
    """Exit criteria: PDF/HTML report generated for at least one strategy run."""

    def test_html_report_generated(self, opt_context: OptContext) -> None:
        optimizer = MeanVarianceOptimizer()
        result = optimizer.run(opt_context)

        portfolio = TargetPortfolio(
            portfolio_id=uuid4(),
            strategy_id="test_strategy",
            as_of_ts=opt_context.as_of_ts,
            nav_currency="USD",
            nav=Decimal("10000"),
            weights=[
                PortfolioWeight(
                    symbol=SYMBOLS[i],
                    weight=Decimal(str(round(result.weights[i], 8))),
                    sector=opt_context.sector_map.get(SYMBOLS[i]),
                )
                for i in range(N_ASSETS)
                if abs(result.weights[i]) > 1e-8
            ],
            status=PortfolioStatus.PASSED,
            optimizer=OptimizerType.MVO,
            optimizer_config_hash="test",
            constraint_set_hash="test",
            covariance_estimator=CovarianceMethod.LEDOIT_WOLF,
            expected_return_source="synthetic",
            risk_report_id=uuid4(),
            created_at=datetime.utcnow(),
        )

        # Build exposure report
        exposure = build_exposure_report(portfolio)

        # Build risk report data
        risk_report = _build_mock_risk_report(portfolio)
        risk_data = build_risk_report_data(
            risk_report=risk_report,
            strategy_id="test_strategy",
            gate_status="passed",
        )

        # Render HTML
        renderer = DailyReportRenderer()
        html = renderer.render_html(
            portfolio=portfolio,
            exposure=exposure,
            risk=risk_data,
        )

        assert len(html) > 1000
        assert "test_strategy" in html
        assert "PASSED" in html
        assert "VaR" in html

    def test_pdf_fallback_to_html(self, opt_context: OptContext) -> None:
        """When WeasyPrint is not available, falls back to HTML file."""
        optimizer = MeanVarianceOptimizer()
        result = optimizer.run(opt_context)

        portfolio = TargetPortfolio(
            portfolio_id=uuid4(),
            strategy_id="test_strategy",
            as_of_ts=opt_context.as_of_ts,
            nav_currency="USD",
            nav=Decimal("10000"),
            weights=[
                PortfolioWeight(
                    symbol=SYMBOLS[i],
                    weight=Decimal(str(round(result.weights[i], 8))),
                )
                for i in range(N_ASSETS)
                if abs(result.weights[i]) > 1e-8
            ],
            status=PortfolioStatus.PASSED,
            optimizer=OptimizerType.MVO,
            optimizer_config_hash="test",
            constraint_set_hash="test",
            covariance_estimator=CovarianceMethod.LEDOIT_WOLF,
            expected_return_source="synthetic",
            risk_report_id=uuid4(),
            created_at=datetime.utcnow(),
        )

        renderer = DailyReportRenderer()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.pdf"
            result_path = renderer.render_pdf(portfolio=portfolio, output_path=output_path)

            # Should produce either .pdf or .html depending on WeasyPrint availability
            assert result_path.exists()
            content = (
                result_path.read_text(encoding="utf-8") if result_path.suffix == ".html" else ""
            )
            if result_path.suffix == ".html":
                assert "test_strategy" in content
