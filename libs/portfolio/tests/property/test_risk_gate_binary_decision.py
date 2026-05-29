"""Property test for Risk Gate binary decision.

**Validates: Requirements 11.1, 11.4**

Property 16: Risk Gate binary decision

The Risk Gate returns a ValidationResult of either "passed" or "rejected"
(binary decision, no partial-pass). All checks must pass for "passed" status.
Any single check failure results in "rejected" status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import hypothesis.strategies as st
from hypothesis import given, settings

from astraeus_portfolio.contracts import (
    ClusterReport,
    ConstraintDiag,
    CovarianceMethod,
    OptimizerType,
    PortfolioStatus,
    PortfolioWeight,
    RiskReport,
    ScenarioName,
    ScenarioResult,
    TargetPortfolio,
)
from astraeus_portfolio.risk.validation import (
    RiskGate,
    RiskPolicy,
    RiskPolicyThresholds,
    ValidationResult,
    ValidationStatus,
)


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

NOW = datetime(2024, 6, 15, 16, 30, 0, tzinfo=timezone.utc)


@st.composite
def st_risk_policy_thresholds(draw: st.DrawFn) -> RiskPolicyThresholds:
    """Generate random but valid risk policy thresholds."""
    return RiskPolicyThresholds(
        cvar_95_hist_max=draw(st.floats(min_value=0.01, max_value=0.10)),
        cvar_99_hist_max=draw(st.floats(min_value=0.02, max_value=0.15)),
        stress_gfc_2008_min=draw(st.floats(min_value=-50.0, max_value=-5.0)),
        stress_covid_2020_min=draw(st.floats(min_value=-50.0, max_value=-5.0)),
        stress_rate_shock_min=draw(st.floats(min_value=-30.0, max_value=-3.0)),
        stress_flash_crash_min=draw(st.floats(min_value=-30.0, max_value=-3.0)),
        max_cluster_weight=draw(st.floats(min_value=0.10, max_value=0.60)),
        beta_deviation_max=draw(st.floats(min_value=0.05, max_value=0.30)),
        beta_target=0.0,
        liquidity_5day_min=draw(st.floats(min_value=0.50, max_value=0.99)),
        single_name_max=draw(st.floats(min_value=0.05, max_value=0.25)),
    )


@st.composite
def st_risk_metrics(draw: st.DrawFn) -> dict:
    """Generate random risk metric values for a RiskReport."""
    return {
        "cvar_95_hist": draw(st.floats(min_value=0.001, max_value=0.15)),
        "cvar_99_hist": draw(st.floats(min_value=0.001, max_value=0.20)),
        "var_95_hist": draw(st.floats(min_value=0.001, max_value=0.10)),
        "var_99_hist": draw(st.floats(min_value=0.001, max_value=0.15)),
        "var_95_param": draw(st.floats(min_value=0.001, max_value=0.10)),
        "cvar_95_param": draw(st.floats(min_value=0.001, max_value=0.10)),
        "var_95_mc": draw(st.floats(min_value=0.001, max_value=0.10)),
        "cvar_95_mc": draw(st.floats(min_value=0.001, max_value=0.10)),
        "stress_gfc_2008": draw(st.floats(min_value=-60.0, max_value=5.0)),
        "stress_covid_2020": draw(st.floats(min_value=-60.0, max_value=5.0)),
        "stress_rate_shock": draw(st.floats(min_value=-40.0, max_value=5.0)),
        "stress_flash_crash": draw(st.floats(min_value=-40.0, max_value=5.0)),
        "max_cluster_weight": draw(st.floats(min_value=0.05, max_value=0.80)),
        "beta": draw(st.floats(min_value=-0.5, max_value=0.5)),
        "liquidity_5day_pct": draw(st.floats(min_value=0.30, max_value=1.0)),
        "max_single_weight": draw(st.floats(min_value=0.01, max_value=0.30)),
    }


def _build_portfolio(max_weight: float) -> TargetPortfolio:
    """Build a minimal TargetPortfolio with a given max single-name weight."""
    # Create weights that include the max weight
    weights = [
        PortfolioWeight(symbol="AAPL", weight=Decimal(str(round(max_weight, 8)))),
        PortfolioWeight(
            symbol="MSFT",
            weight=Decimal(str(round(1.0 - max_weight, 8))),
        ),
    ]
    return TargetPortfolio(
        portfolio_id=uuid4(),
        strategy_id="test_strategy",
        as_of_ts=NOW,
        nav=Decimal("1000000.00"),
        weights=weights,
        status=PortfolioStatus.PASSED,
        optimizer=OptimizerType.MVO,
        optimizer_config_hash="abc123",
        constraint_set_hash="def456",
        covariance_estimator=CovarianceMethod.LEDOIT_WOLF,
        expected_return_source="phase3_signals",
        risk_report_id=uuid4(),
        created_at=NOW,
    )


def _build_risk_report(metrics: dict) -> RiskReport:
    """Build a RiskReport from generated metric values."""
    stress_scenarios = [
        ScenarioResult(
            scenario_name=ScenarioName.GFC_2008,
            scenario_version="v1",
            total_pnl_pct=Decimal(str(round(metrics["stress_gfc_2008"], 2))),
            factor_contributions={},
            asset_contributions={},
        ),
        ScenarioResult(
            scenario_name=ScenarioName.COVID_2020,
            scenario_version="v1",
            total_pnl_pct=Decimal(str(round(metrics["stress_covid_2020"], 2))),
            factor_contributions={},
            asset_contributions={},
        ),
        ScenarioResult(
            scenario_name=ScenarioName.RATE_SHOCK,
            scenario_version="v1",
            total_pnl_pct=Decimal(str(round(metrics["stress_rate_shock"], 2))),
            factor_contributions={},
            asset_contributions={},
        ),
        ScenarioResult(
            scenario_name=ScenarioName.FLASH_CRASH,
            scenario_version="v1",
            total_pnl_pct=Decimal(str(round(metrics["stress_flash_crash"], 2))),
            factor_contributions={},
            asset_contributions={},
        ),
    ]

    cluster_report = ClusterReport(
        max_cluster_weight=Decimal(
            str(round(metrics["max_cluster_weight"], 4))
        ),
        herfindahl_index=Decimal("0.05"),
        effective_n_bets=Decimal("5.0"),
        cluster_assignments={"AAPL": 1, "MSFT": 2},
    )

    return RiskReport(
        report_id=uuid4(),
        portfolio_id=uuid4(),
        as_of_ts=NOW,
        var_95_hist=Decimal(str(round(metrics["var_95_hist"], 6))),
        var_99_hist=Decimal(str(round(metrics["var_99_hist"], 6))),
        cvar_95_hist=Decimal(str(round(metrics["cvar_95_hist"], 6))),
        cvar_99_hist=Decimal(str(round(metrics["cvar_99_hist"], 6))),
        var_95_param=Decimal(str(round(metrics["var_95_param"], 6))),
        cvar_95_param=Decimal(str(round(metrics["cvar_95_param"], 6))),
        var_95_mc=Decimal(str(round(metrics["var_95_mc"], 6))),
        cvar_95_mc=Decimal(str(round(metrics["cvar_95_mc"], 6))),
        stress_scenarios=stress_scenarios,
        cluster_concentration=cluster_report,
        sector_exposure={"Technology": Decimal("0.50")},
        factor_exposure={"MKT": Decimal("0.80")},
        beta=Decimal(str(round(metrics["beta"], 6))),
        effective_n_bets=Decimal("5.0"),
        liquidity_5day_pct=Decimal(str(round(metrics["liquidity_5day_pct"], 4))),
        constraint_diagnostics=[],
        policy_version="v1.0",
    )


# ---------------------------------------------------------------------------
# Property 16: Risk Gate binary decision
# ---------------------------------------------------------------------------


class TestRiskGateBinaryDecision:
    """Property 16: Risk Gate binary decision.

    **Validates: Requirements 11.1, 11.4**

    The Risk Gate always returns either "passed" or "rejected":
    - No partial-pass or warning-only mode
    - All checks must pass for "passed" status
    - Any single check failure results in "rejected" status
    """

    @given(
        thresholds=st_risk_policy_thresholds(),
        metrics=st_risk_metrics(),
    )
    @settings(max_examples=300, deadline=None)
    def test_result_is_always_binary(
        self,
        thresholds: RiskPolicyThresholds,
        metrics: dict,
    ) -> None:
        """The Risk Gate always returns 'passed' or 'rejected', never anything else."""
        gate = RiskGate()
        policy = RiskPolicy(policy_version="v1.0", thresholds=thresholds)

        portfolio = _build_portfolio(metrics["max_single_weight"])
        report = _build_risk_report(metrics)

        result = gate.validate(portfolio, report, policy)

        # Binary decision: only "passed" or "rejected"
        assert result.status in (
            ValidationStatus.PASSED,
            ValidationStatus.REJECTED,
        ), f"Unexpected status: {result.status}"

    @given(
        thresholds=st_risk_policy_thresholds(),
        metrics=st_risk_metrics(),
    )
    @settings(max_examples=300, deadline=None)
    def test_all_checks_pass_implies_passed(
        self,
        thresholds: RiskPolicyThresholds,
        metrics: dict,
    ) -> None:
        """If all checks pass, the result must be 'passed' with no failed checks."""
        gate = RiskGate()
        policy = RiskPolicy(policy_version="v1.0", thresholds=thresholds)

        portfolio = _build_portfolio(metrics["max_single_weight"])
        report = _build_risk_report(metrics)

        result = gate.validate(portfolio, report, policy)

        if result.status == ValidationStatus.PASSED:
            # Passed means zero failed checks
            assert len(result.failed_checks) == 0, (
                f"Status is 'passed' but failed_checks is non-empty: "
                f"{result.failed_checks}"
            )

    @given(
        thresholds=st_risk_policy_thresholds(),
        metrics=st_risk_metrics(),
    )
    @settings(max_examples=300, deadline=None)
    def test_any_failure_implies_rejected(
        self,
        thresholds: RiskPolicyThresholds,
        metrics: dict,
    ) -> None:
        """If any check fails, the result must be 'rejected'."""
        gate = RiskGate()
        policy = RiskPolicy(policy_version="v1.0", thresholds=thresholds)

        portfolio = _build_portfolio(metrics["max_single_weight"])
        report = _build_risk_report(metrics)

        result = gate.validate(portfolio, report, policy)

        if result.failed_checks:
            # Any failure means rejected
            assert result.status == ValidationStatus.REJECTED, (
                f"Has {len(result.failed_checks)} failed checks but status "
                f"is '{result.status}' instead of 'rejected'"
            )

    @given(
        thresholds=st_risk_policy_thresholds(),
        metrics=st_risk_metrics(),
    )
    @settings(max_examples=300, deadline=None)
    def test_passed_iff_no_failed_checks(
        self,
        thresholds: RiskPolicyThresholds,
        metrics: dict,
    ) -> None:
        """'passed' if and only if failed_checks is empty (biconditional)."""
        gate = RiskGate()
        policy = RiskPolicy(policy_version="v1.0", thresholds=thresholds)

        portfolio = _build_portfolio(metrics["max_single_weight"])
        report = _build_risk_report(metrics)

        result = gate.validate(portfolio, report, policy)

        # Biconditional: passed <=> no failed checks
        is_passed = result.status == ValidationStatus.PASSED
        no_failures = len(result.failed_checks) == 0

        assert is_passed == no_failures, (
            f"Biconditional violated: status={result.status}, "
            f"failed_checks count={len(result.failed_checks)}"
        )

    @given(
        thresholds=st_risk_policy_thresholds(),
        metrics=st_risk_metrics(),
    )
    @settings(max_examples=300, deadline=None)
    def test_single_check_failure_causes_rejection(
        self,
        thresholds: RiskPolicyThresholds,
        metrics: dict,
    ) -> None:
        """Verify that even a single check failure results in 'rejected'.

        We manually construct metrics that pass all checks except one,
        then verify the gate rejects.
        """
        gate = RiskGate()
        policy = RiskPolicy(policy_version="v1.0", thresholds=thresholds)

        # Use a small max weight that guarantees both weights in the
        # 2-asset portfolio are below the single_name_max threshold.
        # With 2 assets summing to 1.0, the max individual weight is
        # max(w, 1-w). To ensure both are below threshold, we need
        # w <= threshold AND (1-w) <= threshold, i.e. w in [1-t, t].
        # This is only possible when threshold >= 0.5. For thresholds < 0.5,
        # a 2-asset portfolio can't satisfy the constraint, so we use
        # an equal-weight portfolio with more assets.
        safe_weight = min(thresholds.single_name_max * 0.5, 0.10)

        # Build metrics that pass all checks
        passing_metrics = {
            "cvar_95_hist": thresholds.cvar_95_hist_max * 0.5,
            "cvar_99_hist": thresholds.cvar_99_hist_max * 0.5,
            "var_95_hist": 0.01,
            "var_99_hist": 0.02,
            "var_95_param": 0.01,
            "cvar_95_param": 0.01,
            "var_95_mc": 0.01,
            "cvar_95_mc": 0.01,
            "stress_gfc_2008": thresholds.stress_gfc_2008_min + 5.0,
            "stress_covid_2020": thresholds.stress_covid_2020_min + 5.0,
            "stress_rate_shock": thresholds.stress_rate_shock_min + 5.0,
            "stress_flash_crash": thresholds.stress_flash_crash_min + 5.0,
            "max_cluster_weight": thresholds.max_cluster_weight * 0.5,
            "beta": thresholds.beta_target,
            "liquidity_5day_pct": min(
                thresholds.liquidity_5day_min + 0.05, 1.0
            ),
            "max_single_weight": safe_weight,
        }

        # Build a portfolio where all weights are below the threshold.
        # Use enough assets so that each weight = 1/n < single_name_max.
        n_assets = max(2, int(1.0 / thresholds.single_name_max) + 2)
        equal_weight = round(1.0 / n_assets, 8)
        weights = [
            PortfolioWeight(
                symbol=f"SYM{i}",
                weight=Decimal(str(equal_weight)),
            )
            for i in range(n_assets)
        ]
        portfolio = TargetPortfolio(
            portfolio_id=uuid4(),
            strategy_id="test_strategy",
            as_of_ts=NOW,
            nav=Decimal("1000000.00"),
            weights=weights,
            status=PortfolioStatus.PASSED,
            optimizer=OptimizerType.MVO,
            optimizer_config_hash="abc123",
            constraint_set_hash="def456",
            covariance_estimator=CovarianceMethod.LEDOIT_WOLF,
            expected_return_source="phase3_signals",
            risk_report_id=uuid4(),
            created_at=NOW,
        )
        report = _build_risk_report(passing_metrics)
        baseline = gate.validate(portfolio, report, policy)
        assert baseline.status == ValidationStatus.PASSED, (
            f"Baseline should pass but got {baseline.status} with "
            f"failed_checks={baseline.failed_checks}"
        )

        # Now break exactly one check: CVaR 95% exceeds threshold
        failing_metrics = passing_metrics.copy()
        failing_metrics["cvar_95_hist"] = thresholds.cvar_95_hist_max + 0.01

        report_fail = _build_risk_report(failing_metrics)
        result = gate.validate(portfolio, report_fail, policy)

        assert result.status == ValidationStatus.REJECTED, (
            f"Single check failure should cause rejection but got "
            f"status={result.status}"
        )
        assert len(result.failed_checks) >= 1
        check_names = [fc.check_name for fc in result.failed_checks]
        assert "cvar_95_hist" in check_names
