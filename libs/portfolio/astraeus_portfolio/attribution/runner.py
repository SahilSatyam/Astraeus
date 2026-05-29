"""Attribution orchestration runner.

Coordinates T+1 attribution by running both factor-model (FF5+MOM) and
Brinson-Fachler attribution on realized portfolios. Produces AttributionResult
records for persistence.

This runs as a separate workflow the morning after the portfolio was published,
once realized returns are available from Phase 1.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import numpy as np
import structlog

from astraeus_portfolio.attribution.brinson import BrinsonResult, run_brinson
from astraeus_portfolio.attribution.factor_model import FactorAttributionEngine
from astraeus_portfolio.contracts import AttributionResult

logger = structlog.get_logger(__name__)


class AttributionRunnerError(Exception):
    """Raised when attribution cannot be computed."""

    pass


class AttributionRunner:
    """Orchestrates T+1 attribution for a realized portfolio.

    Runs both factor-model and Brinson attribution, producing two
    AttributionResult records per portfolio per day.
    """

    def __init__(
        self,
        factor_names: list[str] | None = None,
        benchmark_name: str = "SPY",
        min_history_days: int = 60,
    ) -> None:
        """Initialize the attribution runner.

        Args:
            factor_names: Factor names for the factor model (default: FF5+MOM).
            benchmark_name: Benchmark for Brinson attribution.
            min_history_days: Minimum history required for factor regression.
        """
        self.factor_names = factor_names or ["MKT-RF", "SMB", "HML", "RMW", "CMA", "MOM"]
        self.benchmark_name = benchmark_name
        self.min_history_days = min_history_days

    def run_full_attribution(
        self,
        portfolio_id: UUID,
        as_of_date: date,
        portfolio_weights: dict[str, float],
        asset_returns: dict[str, float],
        factor_returns: dict[str, float],
        asset_return_history: np.ndarray | None = None,
        factor_return_history: np.ndarray | None = None,
        benchmark_weights: dict[str, float] | None = None,
        benchmark_returns: dict[str, float] | None = None,
        sector_map: dict[str, str] | None = None,
    ) -> list[AttributionResult]:
        """Run both factor-model and Brinson attribution.

        Args:
            portfolio_id: UUID of the portfolio being attributed.
            as_of_date: The attribution date (T+1 from portfolio publication).
            portfolio_weights: symbol -> beginning-of-period weight.
            asset_returns: symbol -> single-period realized return.
            factor_returns: factor_name -> single-period factor return.
            asset_return_history: (T, n) historical asset returns for regression.
            factor_return_history: (T, k) historical factor returns for regression.
            benchmark_weights: symbol -> benchmark weight (for Brinson).
            benchmark_returns: symbol -> benchmark return (for Brinson).
            sector_map: symbol -> GICS L1 sector.

        Returns:
            List of AttributionResult (one factor-model, one Brinson if data available).
        """
        results: list[AttributionResult] = []
        as_of_ts = datetime.combine(as_of_date, datetime.min.time())

        # --- Factor-model attribution ---
        factor_result = self._run_factor_attribution(
            portfolio_id=portfolio_id,
            as_of_ts=as_of_ts,
            portfolio_weights=portfolio_weights,
            asset_returns=asset_returns,
            factor_returns=factor_returns,
            asset_return_history=asset_return_history,
            factor_return_history=factor_return_history,
        )
        if factor_result is not None:
            results.append(factor_result)

        # --- Brinson attribution ---
        if (
            benchmark_weights is not None
            and benchmark_returns is not None
            and sector_map is not None
        ):
            brinson_result = self._run_brinson_attribution(
                portfolio_id=portfolio_id,
                as_of_ts=as_of_ts,
                portfolio_weights=portfolio_weights,
                asset_returns=asset_returns,
                benchmark_weights=benchmark_weights,
                benchmark_returns=benchmark_returns,
                sector_map=sector_map,
            )
            if brinson_result is not None:
                results.append(brinson_result)

        logger.info(
            "attribution_runner_complete",
            portfolio_id=str(portfolio_id),
            as_of_date=str(as_of_date),
            n_results=len(results),
        )

        return results

    def _run_factor_attribution(
        self,
        portfolio_id: UUID,
        as_of_ts: datetime,
        portfolio_weights: dict[str, float],
        asset_returns: dict[str, float],
        factor_returns: dict[str, float],
        asset_return_history: np.ndarray | None,
        factor_return_history: np.ndarray | None,
    ) -> AttributionResult | None:
        """Run factor-model (FF5+MOM) attribution.

        Returns None if insufficient data for regression.
        """
        start = time.perf_counter()
        logger.info("factor_attribution_start", portfolio_id=str(portfolio_id))

        try:
            if asset_return_history is None or factor_return_history is None:
                logger.warning(
                    "factor_attribution_skipped_no_history",
                    portfolio_id=str(portfolio_id),
                )
                return None

            if asset_return_history.shape[0] < self.min_history_days:
                logger.warning(
                    "factor_attribution_insufficient_history",
                    available=asset_return_history.shape[0],
                    required=self.min_history_days,
                )
                return None

            symbols = list(portfolio_weights.keys())
            len(symbols)
            n_factors = len(self.factor_names)

            # Compute portfolio return
            portfolio_return = sum(
                portfolio_weights[s] * asset_returns.get(s, 0.0) for s in symbols
            )

            # Compute factor PnL contributions using portfolio-level exposure
            # Simple approach: portfolio beta * factor return
            # Full approach would use per-asset betas from FactorAttributionEngine
            engine = FactorAttributionEngine(
                regression_window=min(asset_return_history.shape[0], 252),
                min_history_days=self.min_history_days,
            )

            # Estimate portfolio factor exposures
            weights_array = np.array([portfolio_weights.get(s, 0.0) for s in symbols])
            factor_returns_today = np.array([factor_returns.get(f, 0.0) for f in self.factor_names])

            # Per-asset beta estimation
            betas, _ = engine.estimate_betas_from_asset_returns(
                asset_returns_history=asset_return_history,
                factor_returns_history=factor_return_history,
            )

            # Portfolio factor exposure: B_p = sum(w_i * beta_i)
            portfolio_betas = weights_array @ betas  # (k,)

            # Factor PnL: B_p * f_realized
            factor_pnl_values = portfolio_betas * factor_returns_today
            factor_pnl_bps = {
                self.factor_names[i]: Decimal(str(round(factor_pnl_values[i] * 10000, 4)))
                for i in range(n_factors)
            }

            # Idiosyncratic PnL
            total_factor_pnl = float(np.sum(factor_pnl_values))
            idio_pnl = portfolio_return - total_factor_pnl
            total_pnl_bps = Decimal(str(round(portfolio_return * 10000, 4)))
            idio_pnl_bps = Decimal(str(round(idio_pnl * 10000, 4)))

            elapsed = (time.perf_counter() - start) * 1000
            logger.info(
                "factor_attribution_complete",
                portfolio_id=str(portfolio_id),
                total_pnl_bps=float(total_pnl_bps),
                idio_pnl_bps=float(idio_pnl_bps),
                duration_ms=round(elapsed, 2),
            )

            return AttributionResult(
                run_id=uuid4(),
                portfolio_id=portfolio_id,
                as_of_ts=as_of_ts,
                method="factor_ff5_mom",
                total_pnl_bps=total_pnl_bps,
                factor_pnl=factor_pnl_bps,
                idio_pnl_bps=idio_pnl_bps,
                sector_pnl=None,
                created_at=datetime.utcnow(),
            )

        except Exception as exc:
            logger.error(
                "factor_attribution_failed",
                portfolio_id=str(portfolio_id),
                error=str(exc),
                exc_info=True,
            )
            return None

    def _run_brinson_attribution(
        self,
        portfolio_id: UUID,
        as_of_ts: datetime,
        portfolio_weights: dict[str, float],
        asset_returns: dict[str, float],
        benchmark_weights: dict[str, float],
        benchmark_returns: dict[str, float],
        sector_map: dict[str, str],
    ) -> AttributionResult | None:
        """Run Brinson-Fachler sector attribution."""
        start = time.perf_counter()
        logger.info("brinson_attribution_start", portfolio_id=str(portfolio_id))

        try:
            brinson_result: BrinsonResult = run_brinson(
                portfolio_id=portfolio_id,
                as_of_ts=as_of_ts,
                portfolio_weights=portfolio_weights,
                benchmark_weights=benchmark_weights,
                portfolio_returns=asset_returns,
                benchmark_returns=benchmark_returns,
                sector_map=sector_map,
                benchmark_name=self.benchmark_name,
            )

            elapsed = (time.perf_counter() - start) * 1000
            logger.info(
                "brinson_attribution_complete",
                portfolio_id=str(portfolio_id),
                active_return_bps=float(brinson_result.total_active_return_bps),
                duration_ms=round(elapsed, 2),
            )

            return brinson_result.to_attribution_result()

        except Exception as exc:
            logger.error(
                "brinson_attribution_failed",
                portfolio_id=str(portfolio_id),
                error=str(exc),
                exc_info=True,
            )
            return None
