"""Attribution report generation.

Produces structured attribution data for rendering into HTML/PDF reports:
- Cumulative PnL split into factor and idiosyncratic
- Top 5 contributors and detractors
- Factor decomposition per attribution window (1d, 5d, 30d, ITD)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import structlog

from astraeus_portfolio.contracts import AttributionResult

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FactorContribution:
    """Single factor's PnL contribution."""

    factor: str
    pnl_bps: Decimal
    pct_of_total: Decimal | None = None


@dataclass(frozen=True)
class TopContributor:
    """Top contributor or detractor."""

    symbol: str
    pnl_bps: Decimal
    sector: str | None = None


@dataclass
class AttributionReportData:
    """Full attribution report data structure for template rendering.

    This is the intermediate representation consumed by the HTML/PDF
    template renderer.
    """

    strategy_id: str
    as_of_date: str
    portfolio_id: str
    method: str  # "factor_ff5_mom" or "brinson"

    # Summary
    total_pnl_bps: Decimal = Decimal("0")
    factor_pnl_bps: Decimal = Decimal("0")
    idio_pnl_bps: Decimal = Decimal("0")

    # Factor decomposition
    factor_contributions: list[FactorContribution] = field(default_factory=list)

    # Sector decomposition (Brinson)
    sector_contributions: list[FactorContribution] = field(default_factory=list)

    # Top contributors/detractors
    top_contributors: list[TopContributor] = field(default_factory=list)
    top_detractors: list[TopContributor] = field(default_factory=list)


def build_attribution_report_data(
    attribution: AttributionResult,
    strategy_id: str,
    per_asset_pnl: dict[str, float] | None = None,
    sector_map: dict[str, str] | None = None,
    top_n: int = 5,
) -> AttributionReportData:
    """Build an AttributionReportData from an AttributionResult.

    Args:
        attribution: The computed AttributionResult.
        strategy_id: Strategy identifier.
        per_asset_pnl: symbol -> PnL in bps (for top contributors).
        sector_map: symbol -> sector mapping.
        top_n: Number of top contributors/detractors to include.

    Returns:
        AttributionReportData ready for template rendering.
    """
    report = AttributionReportData(
        strategy_id=strategy_id,
        as_of_date=attribution.as_of_ts.strftime("%Y-%m-%d"),
        portfolio_id=str(attribution.portfolio_id),
        method=attribution.method,
        total_pnl_bps=attribution.total_pnl_bps,
    )

    # --- Factor decomposition ---
    if attribution.factor_pnl:
        total_factor = Decimal("0")
        for factor, pnl in attribution.factor_pnl.items():
            total_factor += pnl
            pct = None
            if attribution.total_pnl_bps != 0:
                pct = (pnl / attribution.total_pnl_bps * 100).quantize(Decimal("0.1"))
            report.factor_contributions.append(
                FactorContribution(factor=factor, pnl_bps=pnl, pct_of_total=pct)
            )
        report.factor_pnl_bps = total_factor

    # --- Idiosyncratic ---
    if attribution.idio_pnl_bps is not None:
        report.idio_pnl_bps = attribution.idio_pnl_bps

    # --- Sector decomposition (Brinson) ---
    if attribution.sector_pnl:
        # Group by sector (strip :allocation/:selection/:interaction suffix)
        sector_totals: dict[str, Decimal] = {}
        for key, pnl in attribution.sector_pnl.items():
            sector = key.split(":")[0]
            sector_totals[sector] = sector_totals.get(sector, Decimal("0")) + pnl

        for sector, pnl in sorted(sector_totals.items(), key=lambda x: x[1], reverse=True):
            pct = None
            if attribution.total_pnl_bps != 0:
                pct = (pnl / attribution.total_pnl_bps * 100).quantize(Decimal("0.1"))
            report.sector_contributions.append(
                FactorContribution(factor=sector, pnl_bps=pnl, pct_of_total=pct)
            )

    # --- Top contributors/detractors ---
    if per_asset_pnl:
        sorted_assets = sorted(per_asset_pnl.items(), key=lambda x: x[1], reverse=True)

        # Top contributors (positive PnL)
        for symbol, pnl in sorted_assets[:top_n]:
            if pnl > 0:
                sector = sector_map.get(symbol) if sector_map else None
                report.top_contributors.append(
                    TopContributor(
                        symbol=symbol,
                        pnl_bps=Decimal(str(round(pnl, 4))),
                        sector=sector,
                    )
                )

        # Top detractors (negative PnL)
        for symbol, pnl in sorted_assets[-top_n:]:
            if pnl < 0:
                sector = sector_map.get(symbol) if sector_map else None
                report.top_detractors.append(
                    TopContributor(
                        symbol=symbol,
                        pnl_bps=Decimal(str(round(pnl, 4))),
                        sector=sector,
                    )
                )

    return report
