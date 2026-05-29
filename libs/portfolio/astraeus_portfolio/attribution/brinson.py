"""Brinson-Fachler sector attribution.

Decomposes active return (portfolio vs benchmark) into three effects per sector:
- Allocation: (w_p_s - w_b_s) * (r_b_s - r_b)
- Selection:  w_b_s * (r_p_s - r_b_s)
- Interaction: (w_p_s - w_b_s) * (r_p_s - r_b_s)

Default benchmark: SPY, sector classification: GICS Level 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import structlog

from astraeus_portfolio.contracts import AttributionResult

logger = structlog.get_logger(__name__)

# Default configuration
DEFAULT_BENCHMARK = "SPY"
DEFAULT_SECTOR_CLASSIFICATION = "GICS_L1"
UNCLASSIFIED_SECTOR = "Unclassified"


@dataclass(frozen=True)
class SectorEffect:
    """Attribution effects for a single sector."""

    sector: str
    allocation_bps: Decimal
    selection_bps: Decimal
    interaction_bps: Decimal

    @property
    def total_bps(self) -> Decimal:
        """Total active return contribution from this sector."""
        return self.allocation_bps + self.selection_bps + self.interaction_bps


@dataclass(frozen=True)
class BrinsonResult:
    """Full Brinson-Fachler attribution result."""

    portfolio_id: UUID
    as_of_ts: datetime
    benchmark: str
    sector_effects: list[SectorEffect]
    total_allocation_bps: Decimal
    total_selection_bps: Decimal
    total_interaction_bps: Decimal
    total_active_return_bps: Decimal
    portfolio_return_bps: Decimal
    benchmark_return_bps: Decimal

    def to_attribution_result(self) -> AttributionResult:
        """Convert to the persistence-layer AttributionResult model."""
        sector_pnl: dict[str, Decimal] = {}
        for effect in self.sector_effects:
            sector_pnl[f"{effect.sector}:allocation"] = effect.allocation_bps
            sector_pnl[f"{effect.sector}:selection"] = effect.selection_bps
            sector_pnl[f"{effect.sector}:interaction"] = effect.interaction_bps

        return AttributionResult(
            run_id=uuid4(),
            portfolio_id=self.portfolio_id,
            as_of_ts=self.as_of_ts,
            method="brinson",
            total_pnl_bps=self.total_active_return_bps,
            factor_pnl=None,
            idio_pnl_bps=None,
            sector_pnl=sector_pnl,
            created_at=datetime.now(),
        )


class BrinsonAttributionError(Exception):
    """Raised when Brinson attribution cannot be computed."""

    pass


@dataclass
class _SectorData:
    """Internal aggregation of sector-level weights and returns."""

    portfolio_weight: float = 0.0
    benchmark_weight: float = 0.0
    portfolio_return: float = 0.0
    benchmark_return: float = 0.0
    # For computing weighted-average returns
    _portfolio_weighted_return: float = field(default=0.0, repr=False)
    _benchmark_weighted_return: float = field(default=0.0, repr=False)


def run_brinson(
    portfolio_id: UUID,
    as_of_ts: datetime,
    portfolio_weights: dict[str, float],
    benchmark_weights: dict[str, float],
    portfolio_returns: dict[str, float],
    benchmark_returns: dict[str, float],
    sector_map: dict[str, str],
    benchmark_name: str = DEFAULT_BENCHMARK,
) -> BrinsonResult:
    """Run Brinson-Fachler sector attribution.

    Args:
        portfolio_id: UUID of the portfolio being attributed.
        as_of_ts: Point-in-time timestamp for the attribution.
        portfolio_weights: Mapping of symbol -> beginning-of-period weight.
        benchmark_weights: Mapping of symbol -> beginning-of-period weight.
        portfolio_returns: Mapping of symbol -> single-period return.
        benchmark_returns: Mapping of symbol -> single-period return.
        sector_map: Mapping of symbol -> GICS Level 1 sector name.
        benchmark_name: Name of the benchmark (default: SPY).

    Returns:
        BrinsonResult with per-sector allocation, selection, and interaction effects.

    Raises:
        BrinsonAttributionError: If fewer than 1 holding has a valid sector classification.
    """
    # Validate: at least 1 holding must have a valid sector classification
    classified_count = sum(1 for symbol in portfolio_weights if symbol in sector_map)
    if classified_count < 1:
        raise BrinsonAttributionError(
            "Insufficient classified holdings: portfolio contains "
            f"{classified_count} holdings with valid sector classification "
            "(minimum 1 required)."
        )

    # Assign sectors to all holdings (unclassified -> "Unclassified")
    all_symbols = set(portfolio_weights.keys()) | set(benchmark_weights.keys())
    symbol_sectors: dict[str, str] = {}
    for symbol in all_symbols:
        symbol_sectors[symbol] = sector_map.get(symbol, UNCLASSIFIED_SECTOR)

    # Aggregate weights and returns by sector
    sectors: dict[str, _SectorData] = {}

    # Process portfolio holdings
    for symbol, weight in portfolio_weights.items():
        sector = symbol_sectors[symbol]
        if sector not in sectors:
            sectors[sector] = _SectorData()
        data = sectors[sector]
        data.portfolio_weight += weight
        ret = portfolio_returns.get(symbol, 0.0)
        data._portfolio_weighted_return += weight * ret

    # Process benchmark holdings
    for symbol, weight in benchmark_weights.items():
        sector = symbol_sectors[symbol]
        if sector not in sectors:
            sectors[sector] = _SectorData()
        data = sectors[sector]
        data.benchmark_weight += weight
        ret = benchmark_returns.get(symbol, 0.0)
        data._benchmark_weighted_return += weight * ret

    # Compute sector-level returns (holding-weighted averages)
    for sector, data in sectors.items():
        if data.portfolio_weight != 0.0:
            data.portfolio_return = data._portfolio_weighted_return / data.portfolio_weight
        else:
            data.portfolio_return = 0.0

        if data.benchmark_weight != 0.0:
            data.benchmark_return = data._benchmark_weighted_return / data.benchmark_weight
        else:
            # Sector in portfolio but not benchmark: benchmark return = 0
            data.benchmark_return = 0.0

    # Compute total benchmark return: r_b = sum(w_b_s * r_b_s)
    total_benchmark_return = sum(
        data.benchmark_weight * data.benchmark_return for data in sectors.values()
    )

    # Compute total portfolio return: r_p = sum(w_p_s * r_p_s)
    total_portfolio_return = sum(
        data.portfolio_weight * data.portfolio_return for data in sectors.values()
    )

    # Compute Brinson-Fachler effects per sector
    sector_effects: list[SectorEffect] = []
    total_allocation = Decimal("0")
    total_selection = Decimal("0")
    total_interaction = Decimal("0")

    for sector, data in sorted(sectors.items()):
        w_p_s = data.portfolio_weight
        w_b_s = data.benchmark_weight
        r_p_s = data.portfolio_return
        r_b_s = data.benchmark_return
        r_b = total_benchmark_return

        # Brinson-Fachler formulas
        allocation = (w_p_s - w_b_s) * (r_b_s - r_b)
        selection = w_b_s * (r_p_s - r_b_s)
        interaction = (w_p_s - w_b_s) * (r_p_s - r_b_s)

        # Convert to bps (multiply by 10000)
        allocation_bps = Decimal(str(allocation * 10000))
        selection_bps = Decimal(str(selection * 10000))
        interaction_bps = Decimal(str(interaction * 10000))

        effect = SectorEffect(
            sector=sector,
            allocation_bps=allocation_bps,
            selection_bps=selection_bps,
            interaction_bps=interaction_bps,
        )
        sector_effects.append(effect)

        total_allocation += allocation_bps
        total_selection += selection_bps
        total_interaction += interaction_bps

    total_active_return_bps = total_allocation + total_selection + total_interaction
    portfolio_return_bps = Decimal(str(total_portfolio_return * 10000))
    benchmark_return_bps = Decimal(str(total_benchmark_return * 10000))

    result = BrinsonResult(
        portfolio_id=portfolio_id,
        as_of_ts=as_of_ts,
        benchmark=benchmark_name,
        sector_effects=sector_effects,
        total_allocation_bps=total_allocation,
        total_selection_bps=total_selection,
        total_interaction_bps=total_interaction,
        total_active_return_bps=total_active_return_bps,
        portfolio_return_bps=portfolio_return_bps,
        benchmark_return_bps=benchmark_return_bps,
    )

    # Verify decomposition: sum of effects should equal active return
    computed_active = float(total_active_return_bps)
    expected_active = (total_portfolio_return - total_benchmark_return) * 10000
    tolerance_bps = 0.01  # 0.01 bps tolerance per requirement 14.5

    if abs(computed_active - expected_active) > tolerance_bps:
        logger.warning(
            "brinson_decomposition_mismatch",
            computed_active_bps=computed_active,
            expected_active_bps=expected_active,
            difference_bps=abs(computed_active - expected_active),
        )

    return result
