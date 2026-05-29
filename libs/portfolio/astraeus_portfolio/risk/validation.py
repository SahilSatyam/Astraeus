"""Risk validation gate: binary pass/fail evaluation.

The Risk Gate evaluates a portfolio against all checks defined in the active
RiskPolicy configuration and returns a ValidationResult of either "passed"
or "rejected". There is no partial-pass or warning-only mode.

All checks must pass for a portfolio to receive "passed" status. Any single
check failure results in "rejected" status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from astraeus_portfolio.contracts import (
    FailedCheck,
    RiskReport,
    ScenarioName,
    TargetPortfolio,
)


# ---------------------------------------------------------------------------
# Validation Result
# ---------------------------------------------------------------------------


class ValidationStatus(StrEnum):
    """Binary validation outcome — no partial-pass."""

    PASSED = "passed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of the Risk Gate evaluation.

    Attributes:
        status: Either "passed" or "rejected" (binary decision).
        failed_checks: List of checks that failed (empty if passed).
        policy_version: Version of the RiskPolicy used for evaluation.
    """

    status: ValidationStatus
    failed_checks: list[FailedCheck] = field(default_factory=list)
    policy_version: str = ""


# ---------------------------------------------------------------------------
# Risk Policy Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskPolicyThresholds:
    """Thresholds for risk gate checks.

    All thresholds use the same sign convention as the RiskReport fields.
    """

    # CVaR thresholds (max allowed, as fraction of NAV)
    cvar_95_hist_max: float = 0.03  # <= 3% NAV
    cvar_99_hist_max: float = 0.05  # <= 5% NAV

    # Stress scenario thresholds (min allowed PnL, as % of NAV)
    stress_gfc_2008_min: float = -25.0  # >= -25% NAV
    stress_covid_2020_min: float = -25.0  # >= -25% NAV
    stress_rate_shock_min: float = -15.0  # >= -15% NAV
    stress_flash_crash_min: float = -15.0  # >= -15% NAV

    # Concentration thresholds
    max_cluster_weight: float = 0.35  # <= 35% portfolio variance

    # Beta deviation
    beta_deviation_max: float = 0.10  # |beta - beta_target| <= 0.10
    beta_target: float = 0.0

    # Liquidity coverage
    liquidity_5day_min: float = 0.90  # >= 90%

    # Single-name weight
    single_name_max: float = 0.12  # <= 12%


@dataclass(frozen=True)
class RiskPolicy:
    """Versioned risk policy configuration."""

    policy_version: str
    thresholds: RiskPolicyThresholds = field(default_factory=RiskPolicyThresholds)


# ---------------------------------------------------------------------------
# Risk Gate
# ---------------------------------------------------------------------------


class RiskGate:
    """Binary pass/fail validation gate.

    Evaluates a portfolio against all checks defined in the active RiskPolicy
    configuration. Returns a ValidationResult of either "passed" or "rejected".
    All checks must pass for "passed" status — no partial-pass or warning-only
    mode.
    """

    def validate(
        self,
        portfolio: TargetPortfolio,
        report: RiskReport,
        policy: RiskPolicy,
    ) -> ValidationResult:
        """Evaluate portfolio against all policy checks.

        Args:
            portfolio: The candidate portfolio to validate.
            report: The computed risk report for the portfolio.
            policy: The active risk policy with thresholds.

        Returns:
            ValidationResult with status "passed" or "rejected".
        """
        thresholds = policy.thresholds
        failed: list[FailedCheck] = []

        # --- CVaR checks ---
        self._check_upper_bound(
            failed,
            check_name="cvar_95_hist",
            actual=float(report.cvar_95_hist),
            threshold=thresholds.cvar_95_hist_max,
        )
        self._check_upper_bound(
            failed,
            check_name="cvar_99_hist",
            actual=float(report.cvar_99_hist),
            threshold=thresholds.cvar_99_hist_max,
        )

        # --- Stress scenario checks ---
        scenario_thresholds = {
            ScenarioName.GFC_2008: thresholds.stress_gfc_2008_min,
            ScenarioName.COVID_2020: thresholds.stress_covid_2020_min,
            ScenarioName.RATE_SHOCK: thresholds.stress_rate_shock_min,
            ScenarioName.FLASH_CRASH: thresholds.stress_flash_crash_min,
        }
        for scenario in report.stress_scenarios:
            min_threshold = scenario_thresholds.get(scenario.scenario_name)
            if min_threshold is not None:
                self._check_lower_bound(
                    failed,
                    check_name=f"stress_{scenario.scenario_name}",
                    actual=float(scenario.total_pnl_pct),
                    threshold=min_threshold,
                )

        # --- Cluster concentration check ---
        self._check_upper_bound(
            failed,
            check_name="max_cluster_weight",
            actual=float(report.cluster_concentration.max_cluster_weight),
            threshold=thresholds.max_cluster_weight,
        )

        # --- Beta deviation check ---
        beta_deviation = abs(float(report.beta) - thresholds.beta_target)
        self._check_upper_bound(
            failed,
            check_name="beta_deviation",
            actual=beta_deviation,
            threshold=thresholds.beta_deviation_max,
        )

        # --- Liquidity coverage check ---
        self._check_lower_bound(
            failed,
            check_name="liquidity_5day_pct",
            actual=float(report.liquidity_5day_pct),
            threshold=thresholds.liquidity_5day_min,
        )

        # --- Single-name weight check ---
        max_weight = max(
            abs(float(pw.weight)) for pw in portfolio.weights
        )
        self._check_upper_bound(
            failed,
            check_name="single_name_weight",
            actual=max_weight,
            threshold=thresholds.single_name_max,
        )

        # --- Binary decision: all checks must pass ---
        if failed:
            status = ValidationStatus.REJECTED
        else:
            status = ValidationStatus.PASSED

        return ValidationResult(
            status=status,
            failed_checks=failed,
            policy_version=policy.policy_version,
        )

    @staticmethod
    def _check_upper_bound(
        failed: list[FailedCheck],
        check_name: str,
        actual: float,
        threshold: float,
    ) -> None:
        """Fail if actual > threshold."""
        if actual > threshold:
            failed.append(
                FailedCheck(
                    check_name=check_name,
                    threshold=threshold,
                    actual_value=actual,
                )
            )

    @staticmethod
    def _check_lower_bound(
        failed: list[FailedCheck],
        check_name: str,
        actual: float,
        threshold: float,
    ) -> None:
        """Fail if actual < threshold."""
        if actual < threshold:
            failed.append(
                FailedCheck(
                    check_name=check_name,
                    threshold=threshold,
                    actual_value=actual,
                )
            )
