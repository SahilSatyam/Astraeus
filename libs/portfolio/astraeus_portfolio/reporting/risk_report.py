"""Risk report generation.

Produces structured risk data for rendering into HTML/PDF reports:
- VaR/CVaR table at 95%/99% with all three methods
- Stress scenario PnLs with thresholds
- Constraint diagnostics (tightest constraint, shadow prices)
- Hedging effectiveness (informational)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import structlog

from astraeus_portfolio.contracts import (
    RiskReport,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class VaRTableEntry:
    """Single row in the VaR/CVaR comparison table."""

    confidence: str  # "95%" or "99%"
    metric: str  # "VaR" or "CVaR"
    historical: Decimal
    parametric: Decimal | None = None
    monte_carlo: Decimal | None = None
    discrepancy_flag: bool = False  # True if methods disagree significantly


@dataclass(frozen=True)
class StressScenarioEntry:
    """Single stress scenario result for the report."""

    scenario_name: str
    total_pnl_pct: Decimal
    threshold: Decimal
    breached: bool
    factor_contributions: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class ConstraintDiagEntry:
    """Constraint diagnostic for the report."""

    constraint_name: str
    satisfied: bool
    shadow_price: float | None = None
    slack: float | None = None
    is_tightest: bool = False


@dataclass
class RiskReportData:
    """Full risk report data structure for template rendering.

    This is the intermediate representation consumed by the HTML/PDF
    template renderer.
    """

    strategy_id: str
    as_of_date: str
    portfolio_id: str

    # VaR/CVaR table
    var_table: list[VaRTableEntry] = field(default_factory=list)

    # Stress scenarios
    stress_scenarios: list[StressScenarioEntry] = field(default_factory=list)

    # Concentration
    max_cluster_weight: Decimal = Decimal("0")
    effective_n_bets: Decimal = Decimal("0")
    herfindahl_index: Decimal = Decimal("0")

    # Beta
    portfolio_beta: Decimal = Decimal("0")
    beta_target: Decimal = Decimal("0")
    beta_deviation: Decimal = Decimal("0")

    # Liquidity
    liquidity_5day_pct: Decimal = Decimal("0")

    # Constraint diagnostics
    constraint_diagnostics: list[ConstraintDiagEntry] = field(default_factory=list)
    tightest_constraint: str | None = None

    # Overall
    gate_status: str = "unknown"  # "passed" or "rejected"
    n_failed_checks: int = 0


# Default stress thresholds (from risk policy)
DEFAULT_STRESS_THRESHOLDS = {
    "gfc_2008": Decimal("-25.0"),
    "covid_2020": Decimal("-25.0"),
    "rate_shock": Decimal("-15.0"),
    "flash_crash": Decimal("-15.0"),
}

# Discrepancy threshold: flag if historical and parametric VaR differ by >50%
DISCREPANCY_THRESHOLD = 0.5


def build_risk_report_data(
    risk_report: RiskReport,
    strategy_id: str,
    gate_status: str = "unknown",
    n_failed_checks: int = 0,
    stress_thresholds: dict[str, Decimal] | None = None,
) -> RiskReportData:
    """Build a RiskReportData from a RiskReport for template rendering.

    Args:
        risk_report: The computed RiskReport from the risk engine.
        strategy_id: Strategy identifier.
        gate_status: Result of the risk gate ("passed" or "rejected").
        n_failed_checks: Number of failed gate checks.
        stress_thresholds: Custom stress thresholds (uses defaults if None).

    Returns:
        RiskReportData ready for template rendering.
    """
    thresholds = stress_thresholds or DEFAULT_STRESS_THRESHOLDS

    report = RiskReportData(
        strategy_id=strategy_id,
        as_of_date=risk_report.as_of_ts.strftime("%Y-%m-%d"),
        portfolio_id=str(risk_report.portfolio_id),
        gate_status=gate_status,
        n_failed_checks=n_failed_checks,
    )

    # --- VaR/CVaR table ---
    # 95% VaR
    hist_var_95 = risk_report.var_95_hist
    param_var_95 = risk_report.var_95_param
    mc_var_95 = risk_report.var_95_mc
    discrepancy_95_var = _check_discrepancy(hist_var_95, param_var_95)

    report.var_table.append(
        VaRTableEntry(
            confidence="95%",
            metric="VaR",
            historical=hist_var_95,
            parametric=param_var_95,
            monte_carlo=mc_var_95,
            discrepancy_flag=discrepancy_95_var,
        )
    )

    # 99% VaR
    report.var_table.append(
        VaRTableEntry(
            confidence="99%",
            metric="VaR",
            historical=risk_report.var_99_hist,
            parametric=None,  # Only 95% parametric in schema
            monte_carlo=None,
            discrepancy_flag=False,
        )
    )

    # 95% CVaR
    hist_cvar_95 = risk_report.cvar_95_hist
    param_cvar_95 = risk_report.cvar_95_param
    mc_cvar_95 = risk_report.cvar_95_mc
    discrepancy_95_cvar = _check_discrepancy(hist_cvar_95, param_cvar_95)

    report.var_table.append(
        VaRTableEntry(
            confidence="95%",
            metric="CVaR",
            historical=hist_cvar_95,
            parametric=param_cvar_95,
            monte_carlo=mc_cvar_95,
            discrepancy_flag=discrepancy_95_cvar,
        )
    )

    # 99% CVaR
    report.var_table.append(
        VaRTableEntry(
            confidence="99%",
            metric="CVaR",
            historical=risk_report.cvar_99_hist,
            parametric=None,
            monte_carlo=None,
            discrepancy_flag=False,
        )
    )

    # --- Stress scenarios ---
    for scenario in risk_report.stress_scenarios:
        threshold = thresholds.get(scenario.scenario_name.value, Decimal("-25.0"))
        breached = scenario.total_pnl_pct < threshold
        report.stress_scenarios.append(
            StressScenarioEntry(
                scenario_name=scenario.scenario_name.value,
                total_pnl_pct=scenario.total_pnl_pct,
                threshold=threshold,
                breached=breached,
                factor_contributions=scenario.factor_contributions,
            )
        )

    # --- Concentration ---
    report.max_cluster_weight = risk_report.cluster_concentration.max_cluster_weight
    report.effective_n_bets = risk_report.cluster_concentration.effective_n_bets
    report.herfindahl_index = risk_report.cluster_concentration.herfindahl_index

    # --- Beta ---
    report.portfolio_beta = risk_report.beta
    report.beta_deviation = abs(risk_report.beta)

    # --- Liquidity ---
    report.liquidity_5day_pct = risk_report.liquidity_5day_pct

    # --- Constraint diagnostics ---
    tightest_shadow = None
    tightest_name = None

    for diag in risk_report.constraint_diagnostics:
        shadow = diag.shadow_price
        if shadow is not None and (tightest_shadow is None or abs(shadow) > abs(tightest_shadow)):
            tightest_shadow = shadow
            tightest_name = diag.constraint_name

        report.constraint_diagnostics.append(
            ConstraintDiagEntry(
                constraint_name=diag.constraint_name,
                satisfied=diag.satisfied,
                shadow_price=diag.shadow_price,
                slack=diag.slack,
            )
        )

    # Mark the tightest constraint
    if tightest_name:
        report.tightest_constraint = tightest_name
        for entry in report.constraint_diagnostics:
            if entry.constraint_name == tightest_name:
                # Recreate as frozen dataclass with is_tightest=True
                idx = report.constraint_diagnostics.index(entry)
                report.constraint_diagnostics[idx] = ConstraintDiagEntry(
                    constraint_name=entry.constraint_name,
                    satisfied=entry.satisfied,
                    shadow_price=entry.shadow_price,
                    slack=entry.slack,
                    is_tightest=True,
                )
                break

    return report


def _check_discrepancy(hist: Decimal, param: Decimal | None) -> bool:
    """Check if historical and parametric VaR/CVaR disagree significantly."""
    if param is None:
        return False
    hist_f = float(hist)
    param_f = float(param)
    if abs(hist_f) < 1e-8:
        return abs(param_f) > 1e-4
    ratio = abs(param_f - hist_f) / abs(hist_f)
    return ratio > DISCREPANCY_THRESHOLD
