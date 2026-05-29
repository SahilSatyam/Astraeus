"""Exposure report generation.

Produces structured exposure data for rendering into HTML/PDF reports:
- Sector exposure (GICS L1) with policy caps overlaid
- Factor exposure (FF5+MOM) with prior-day delta callouts
- Top-N concentration with cluster assignments
- Position changes vs prior day
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog

from astraeus_portfolio.contracts import PortfolioWeight, TargetPortfolio

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SectorExposureEntry:
    """Single sector exposure entry."""

    sector: str
    weight: Decimal
    policy_cap: Decimal | None = None
    utilization_pct: Decimal | None = None  # weight / cap


@dataclass(frozen=True)
class FactorExposureEntry:
    """Single factor exposure entry."""

    factor: str
    exposure: Decimal
    prior_exposure: Decimal | None = None
    delta: Decimal | None = None


@dataclass(frozen=True)
class ConcentrationEntry:
    """Top-N concentration entry."""

    symbol: str
    weight: Decimal
    sector: str | None
    cluster_id: int | None = None


@dataclass(frozen=True)
class PositionChange:
    """Position change vs prior day."""

    symbol: str
    current_weight: Decimal
    prior_weight: Decimal
    delta: Decimal
    sector: str | None = None
    is_liquidity_bound: bool = False


@dataclass
class ExposureReport:
    """Full exposure report data structure.

    This is the intermediate representation consumed by the HTML/PDF
    template renderer.
    """

    strategy_id: str
    as_of_date: str
    sector_exposures: list[SectorExposureEntry] = field(default_factory=list)
    factor_exposures: list[FactorExposureEntry] = field(default_factory=list)
    top_n_concentration: list[ConcentrationEntry] = field(default_factory=list)
    position_changes: list[PositionChange] = field(default_factory=list)
    total_long: Decimal = Decimal("0")
    total_short: Decimal = Decimal("0")
    net_exposure: Decimal = Decimal("0")
    gross_exposure: Decimal = Decimal("0")
    n_positions: int = 0


def build_exposure_report(
    portfolio: TargetPortfolio,
    prior_portfolio: TargetPortfolio | None = None,
    factor_exposures: dict[str, float] | None = None,
    prior_factor_exposures: dict[str, float] | None = None,
    cluster_assignments: dict[str, int] | None = None,
    sector_caps: dict[str, float] | None = None,
    top_n: int = 10,
) -> ExposureReport:
    """Build an exposure report from a portfolio.

    Args:
        portfolio: The target portfolio to report on.
        prior_portfolio: Previous day's portfolio for delta computation.
        factor_exposures: Current factor exposures {factor: exposure}.
        prior_factor_exposures: Prior day's factor exposures.
        cluster_assignments: symbol -> cluster_id mapping.
        sector_caps: sector -> max_weight policy caps.
        top_n: Number of top positions to include in concentration.

    Returns:
        ExposureReport with all sections populated.
    """
    report = ExposureReport(
        strategy_id=portfolio.strategy_id,
        as_of_date=portfolio.as_of_ts.strftime("%Y-%m-%d"),
    )

    # --- Basic exposure metrics ---
    total_long = Decimal("0")
    total_short = Decimal("0")
    for pw in portfolio.weights:
        if pw.weight > 0:
            total_long += pw.weight
        else:
            total_short += abs(pw.weight)

    report.total_long = total_long
    report.total_short = total_short
    report.net_exposure = total_long - total_short
    report.gross_exposure = total_long + total_short
    report.n_positions = len([pw for pw in portfolio.weights if abs(pw.weight) > Decimal("0.0001")])

    # --- Sector exposure ---
    sector_weights: dict[str, Decimal] = {}
    for pw in portfolio.weights:
        sector = pw.sector or "Unclassified"
        sector_weights[sector] = sector_weights.get(sector, Decimal("0")) + abs(pw.weight)

    default_cap = Decimal("0.25")
    for sector, weight in sorted(sector_weights.items(), key=lambda x: x[1], reverse=True):
        cap = Decimal(str(sector_caps.get(sector, 0.25))) if sector_caps else default_cap
        utilization = (weight / cap * 100) if cap > 0 else None
        report.sector_exposures.append(
            SectorExposureEntry(
                sector=sector,
                weight=weight,
                policy_cap=cap,
                utilization_pct=utilization,
            )
        )

    # --- Factor exposure ---
    if factor_exposures:
        for factor, exposure in factor_exposures.items():
            prior_exp = prior_factor_exposures.get(factor) if prior_factor_exposures else None
            delta = None
            if prior_exp is not None:
                delta = Decimal(str(round(exposure - prior_exp, 6)))
            report.factor_exposures.append(
                FactorExposureEntry(
                    factor=factor,
                    exposure=Decimal(str(round(exposure, 6))),
                    prior_exposure=Decimal(str(round(prior_exp, 6))) if prior_exp is not None else None,
                    delta=delta,
                )
            )

    # --- Top-N concentration ---
    sorted_weights = sorted(portfolio.weights, key=lambda pw: abs(pw.weight), reverse=True)
    for pw in sorted_weights[:top_n]:
        cluster_id = cluster_assignments.get(pw.symbol) if cluster_assignments else None
        report.top_n_concentration.append(
            ConcentrationEntry(
                symbol=pw.symbol,
                weight=pw.weight,
                sector=pw.sector,
                cluster_id=cluster_id,
            )
        )

    # --- Position changes ---
    if prior_portfolio is not None:
        prior_weight_map: dict[str, Decimal] = {
            pw.symbol: pw.weight for pw in prior_portfolio.weights
        }
        current_weight_map: dict[str, Decimal] = {
            pw.symbol: pw.weight for pw in portfolio.weights
        }

        all_symbols = set(prior_weight_map.keys()) | set(current_weight_map.keys())
        changes: list[PositionChange] = []

        for symbol in all_symbols:
            current = current_weight_map.get(symbol, Decimal("0"))
            prior = prior_weight_map.get(symbol, Decimal("0"))
            delta = current - prior
            if abs(delta) > Decimal("0.0005"):  # 5 bps minimum trade size
                sector = None
                for pw in portfolio.weights:
                    if pw.symbol == symbol:
                        sector = pw.sector
                        break
                changes.append(
                    PositionChange(
                        symbol=symbol,
                        current_weight=current,
                        prior_weight=prior,
                        delta=delta,
                        sector=sector,
                    )
                )

        # Sort by absolute trade size descending
        changes.sort(key=lambda c: abs(c.delta), reverse=True)
        report.position_changes = changes

    return report
