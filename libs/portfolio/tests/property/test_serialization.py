"""Property tests for TargetPortfolio and RiskReport serialization round-trip.

**Validates: Requirements 17.1, 17.2, 17.6**

These tests verify that arbitrary valid instances of TargetPortfolio and RiskReport
survive both dict-based (model_dump → model_validate) and JSON-based
(model_dump_json → model_validate_json) round-trips without data loss or mutation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

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

# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Valid UUIDs
st_uuid = st.uuids()

# UTC datetimes (avoid extreme values that may not serialize cleanly)
st_datetime = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.just(timezone.utc),
)

# Decimals within reasonable financial ranges
st_decimal_weight = st.decimals(
    min_value=Decimal("-1.0"),
    max_value=Decimal("1.0"),
    places=8,
    allow_nan=False,
    allow_infinity=False,
)

st_decimal_positive = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("9999999.99"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)

st_decimal_pct = st.decimals(
    min_value=Decimal("-99.99"),
    max_value=Decimal("99.99"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)

st_decimal_small = st.decimals(
    min_value=Decimal("0.0001"),
    max_value=Decimal("999.9999"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)

# Short strings for identifiers (alphanumeric only to avoid JSON encoding issues)
st_symbol = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Nd")),
    min_size=1,
    max_size=10,
)

st_short_string = st.text(
    alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc")),
    min_size=1,
    max_size=32,
)

st_medium_string = st.text(
    alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc")),
    min_size=1,
    max_size=64,
)

# Enum strategies
st_optimizer_type = st.sampled_from(list(OptimizerType))
st_covariance_method = st.sampled_from(list(CovarianceMethod))
st_portfolio_status = st.sampled_from(list(PortfolioStatus))
st_scenario_name = st.sampled_from(list(ScenarioName))


# ---------------------------------------------------------------------------
# Composite Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_portfolio_weight(draw: st.DrawFn) -> PortfolioWeight:
    """Generate a valid PortfolioWeight instance."""
    return PortfolioWeight(
        symbol=draw(st_symbol),
        weight=draw(st_decimal_weight),
        sector=draw(st.one_of(st.none(), st_short_string)),
    )


@st.composite
def st_scenario_result(draw: st.DrawFn) -> ScenarioResult:
    """Generate a valid ScenarioResult instance."""
    n_factors = draw(st.integers(min_value=0, max_value=3))
    n_assets = draw(st.integers(min_value=0, max_value=3))

    factor_contributions = {
        draw(st_short_string): draw(st_decimal_pct) for _ in range(n_factors)
    }
    asset_contributions = {
        draw(st_symbol): draw(st_decimal_pct) for _ in range(n_assets)
    }

    return ScenarioResult(
        scenario_name=draw(st_scenario_name),
        scenario_version=draw(st_short_string),
        total_pnl_pct=draw(st_decimal_pct),
        factor_contributions=factor_contributions,
        asset_contributions=asset_contributions,
        proxy_estimated_assets=draw(
            st.lists(st_symbol, min_size=0, max_size=3)
        ),
    )


@st.composite
def st_cluster_report(draw: st.DrawFn) -> ClusterReport:
    """Generate a valid ClusterReport instance."""
    n_assignments = draw(st.integers(min_value=1, max_value=5))
    cluster_assignments = {
        draw(st_symbol): draw(st.integers(min_value=0, max_value=9))
        for _ in range(n_assignments)
    }

    return ClusterReport(
        n_clusters=draw(st.integers(min_value=1, max_value=20)),
        max_cluster_weight=draw(st_decimal_small),
        herfindahl_index=draw(st_decimal_small),
        effective_n_bets=draw(st_decimal_small),
        cluster_assignments=cluster_assignments,
    )


@st.composite
def st_constraint_diag(draw: st.DrawFn) -> ConstraintDiag:
    """Generate a valid ConstraintDiag instance."""
    return ConstraintDiag(
        constraint_name=draw(st_short_string),
        satisfied=draw(st.booleans()),
        shadow_price=draw(
            st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False))
        ),
        slack=draw(
            st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False))
        ),
        diagnostic=draw(
            st.fixed_dictionaries(
                {
                    "status": st_short_string,
                    "value": st.floats(allow_nan=False, allow_infinity=False),
                }
            )
        ),
    )


@st.composite
def st_target_portfolio(draw: st.DrawFn) -> TargetPortfolio:
    """Generate a valid TargetPortfolio instance."""
    return TargetPortfolio(
        portfolio_id=draw(st_uuid),
        strategy_id=draw(st_medium_string),
        as_of_ts=draw(st_datetime),
        nav_currency=draw(st.sampled_from(["USD", "EUR", "GBP", "JPY"])),
        nav=draw(st_decimal_positive),
        weights=draw(st.lists(st_portfolio_weight(), min_size=1, max_size=10)),
        status=draw(st_portfolio_status),
        optimizer=draw(st_optimizer_type),
        optimizer_config_hash=draw(st_medium_string),
        constraint_set_hash=draw(st_medium_string),
        covariance_estimator=draw(st_covariance_method),
        expected_return_source=draw(st_medium_string),
        risk_report_id=draw(st_uuid),
        rejection_id=draw(st.one_of(st.none(), st_uuid)),
        parent_portfolio_id=draw(st.one_of(st.none(), st_uuid)),
        created_at=draw(st_datetime),
        schema_version="v1",
    )


@st.composite
def st_risk_report(draw: st.DrawFn) -> RiskReport:
    """Generate a valid RiskReport instance."""
    n_sectors = draw(st.integers(min_value=0, max_value=5))
    n_factors = draw(st.integers(min_value=0, max_value=5))

    sector_exposure = {
        draw(st_short_string): draw(st_decimal_pct) for _ in range(n_sectors)
    }
    factor_exposure = {
        draw(st_short_string): draw(st_decimal_pct) for _ in range(n_factors)
    }

    return RiskReport(
        report_id=draw(st_uuid),
        portfolio_id=draw(st_uuid),
        as_of_ts=draw(st_datetime),
        var_95_hist=draw(st_decimal_pct),
        var_99_hist=draw(st_decimal_pct),
        cvar_95_hist=draw(st_decimal_pct),
        cvar_99_hist=draw(st_decimal_pct),
        var_95_param=draw(st_decimal_pct),
        cvar_95_param=draw(st_decimal_pct),
        var_95_mc=draw(st_decimal_pct),
        cvar_95_mc=draw(st_decimal_pct),
        stress_scenarios=draw(
            st.lists(st_scenario_result(), min_size=0, max_size=5)
        ),
        cluster_concentration=draw(st_cluster_report()),
        sector_exposure=sector_exposure,
        factor_exposure=factor_exposure,
        beta=draw(st_decimal_pct),
        effective_n_bets=draw(st_decimal_small),
        liquidity_5day_pct=draw(st_decimal_small),
        constraint_diagnostics=draw(
            st.lists(st_constraint_diag(), min_size=0, max_size=5)
        ),
        policy_version=draw(st_short_string),
        schema_version="v1",
    )


# ---------------------------------------------------------------------------
# Property 21: TargetPortfolio serialization round-trip
# ---------------------------------------------------------------------------


class TestTargetPortfolioRoundTrip:
    """Property 21: TargetPortfolio serialization round-trip.

    **Validates: Requirements 17.1, 17.6**

    For any valid TargetPortfolio instance, serializing and deserializing
    via both dict and JSON paths produces an identical object.
    """

    @given(portfolio=st_target_portfolio())
    @settings(max_examples=200, deadline=None)
    def test_dict_roundtrip_preserves_equality(
        self, portfolio: TargetPortfolio
    ) -> None:
        """model_dump() → model_validate() produces an identical TargetPortfolio."""
        dumped = portfolio.model_dump()
        restored = TargetPortfolio.model_validate(dumped)
        assert restored == portfolio

    @given(portfolio=st_target_portfolio())
    @settings(max_examples=200, deadline=None)
    def test_json_roundtrip_preserves_equality(
        self, portfolio: TargetPortfolio
    ) -> None:
        """model_dump_json() → model_validate_json() produces an identical TargetPortfolio."""
        json_str = portfolio.model_dump_json()
        restored = TargetPortfolio.model_validate_json(json_str)
        assert restored == portfolio

    @given(portfolio=st_target_portfolio())
    @settings(max_examples=100, deadline=None)
    def test_roundtrip_preserves_types(self, portfolio: TargetPortfolio) -> None:
        """Round-trip preserves field types (UUID, Decimal, datetime, enums)."""
        dumped = portfolio.model_dump()
        restored = TargetPortfolio.model_validate(dumped)

        assert isinstance(restored.portfolio_id, UUID)
        assert isinstance(restored.nav, Decimal)
        assert isinstance(restored.as_of_ts, datetime)
        assert isinstance(restored.status, PortfolioStatus)
        assert isinstance(restored.optimizer, OptimizerType)
        assert isinstance(restored.covariance_estimator, CovarianceMethod)
        assert isinstance(restored.schema_version, str)
        assert len(restored.weights) >= 1
        assert len(restored.weights) <= 500
        for w in restored.weights:
            assert isinstance(w.weight, Decimal)
            assert w.weight >= Decimal("-1.0")
            assert w.weight <= Decimal("1.0")

    @given(portfolio=st_target_portfolio())
    @settings(max_examples=100, deadline=None)
    def test_json_roundtrip_preserves_types(
        self, portfolio: TargetPortfolio
    ) -> None:
        """JSON round-trip preserves field types."""
        json_str = portfolio.model_dump_json()
        restored = TargetPortfolio.model_validate_json(json_str)

        assert isinstance(restored.portfolio_id, UUID)
        assert isinstance(restored.nav, Decimal)
        assert isinstance(restored.as_of_ts, datetime)
        assert isinstance(restored.status, PortfolioStatus)
        assert isinstance(restored.optimizer, OptimizerType)
        assert isinstance(restored.covariance_estimator, CovarianceMethod)
        for w in restored.weights:
            assert isinstance(w.weight, Decimal)
            assert w.weight >= Decimal("-1.0")
            assert w.weight <= Decimal("1.0")


# ---------------------------------------------------------------------------
# Property 22: RiskReport serialization round-trip
# ---------------------------------------------------------------------------


class TestRiskReportRoundTrip:
    """Property 22: RiskReport serialization round-trip.

    **Validates: Requirements 17.2, 17.6**

    For any valid RiskReport instance, serializing and deserializing
    via both dict and JSON paths produces an identical object.
    """

    @given(report=st_risk_report())
    @settings(max_examples=200, deadline=None)
    def test_dict_roundtrip_preserves_equality(self, report: RiskReport) -> None:
        """model_dump() → model_validate() produces an identical RiskReport."""
        dumped = report.model_dump()
        restored = RiskReport.model_validate(dumped)
        assert restored == report

    @given(report=st_risk_report())
    @settings(max_examples=200, deadline=None)
    def test_json_roundtrip_preserves_equality(self, report: RiskReport) -> None:
        """model_dump_json() → model_validate_json() produces an identical RiskReport."""
        json_str = report.model_dump_json()
        restored = RiskReport.model_validate_json(json_str)
        assert restored == report

    @given(report=st_risk_report())
    @settings(max_examples=100, deadline=None)
    def test_dict_roundtrip_preserves_types(self, report: RiskReport) -> None:
        """Round-trip preserves field types (UUID, Decimal, datetime, nested models)."""
        dumped = report.model_dump()
        restored = RiskReport.model_validate(dumped)

        assert isinstance(restored.report_id, UUID)
        assert isinstance(restored.portfolio_id, UUID)
        assert isinstance(restored.as_of_ts, datetime)
        assert isinstance(restored.var_95_hist, Decimal)
        assert isinstance(restored.beta, Decimal)
        assert isinstance(restored.effective_n_bets, Decimal)
        assert isinstance(restored.cluster_concentration, ClusterReport)
        assert isinstance(restored.schema_version, str)
        assert len(restored.stress_scenarios) <= 20
        assert len(restored.constraint_diagnostics) <= 50
        for scenario in restored.stress_scenarios:
            assert isinstance(scenario, ScenarioResult)
            assert isinstance(scenario.scenario_name, ScenarioName)
            assert isinstance(scenario.total_pnl_pct, Decimal)
        for diag in restored.constraint_diagnostics:
            assert isinstance(diag, ConstraintDiag)

    @given(report=st_risk_report())
    @settings(max_examples=100, deadline=None)
    def test_json_roundtrip_preserves_types(self, report: RiskReport) -> None:
        """JSON round-trip preserves field types."""
        json_str = report.model_dump_json()
        restored = RiskReport.model_validate_json(json_str)

        assert isinstance(restored.report_id, UUID)
        assert isinstance(restored.portfolio_id, UUID)
        assert isinstance(restored.as_of_ts, datetime)
        assert isinstance(restored.var_95_hist, Decimal)
        assert isinstance(restored.beta, Decimal)
        assert isinstance(restored.effective_n_bets, Decimal)
        assert isinstance(restored.cluster_concentration, ClusterReport)
        assert len(restored.stress_scenarios) <= 20
        assert len(restored.constraint_diagnostics) <= 50
        for scenario in restored.stress_scenarios:
            assert isinstance(scenario, ScenarioResult)
            assert isinstance(scenario.scenario_name, ScenarioName)
