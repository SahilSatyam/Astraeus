"""Historical data fitting for HMM and GMM regime models.

Pulls historical macro/vol features from the feature store and fits
the regime detection models. Designed to be run periodically (monthly)
as a rolling refit.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog

from .detector import RegimeDetector

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.regime.fitting")

# Features used for regime detection — macro/vol indicators
REGIME_FEATURES = [
    "low_vol_60d",
    "momentum_12_1",
]

# Additional macro features when available
EXTENDED_REGIME_FEATURES = [
    "vix_level",
    "vol_spread_term_structure",
    "macro_credit_spread",
    "macro_yield_curve_slope",
    "rate_10y_change_20d",
]


async def fit_regime_models(
    session: AsyncSession,
    detector: RegimeDetector,
    symbols: list[str],
    lookback_days: int = 756,  # ~3 years
    as_of_date: date | None = None,
    feature_names: list[str] | None = None,
) -> dict[str, Any]:
    """Fit HMM and GMM models on historical feature data.

    Pulls daily feature snapshots for the lookback period and fits
    both the HMM (temporal) and GMM (cross-sectional) models.

    Args:
        session: Database session for feature retrieval.
        detector: RegimeDetector instance to fit.
        symbols: Universe symbols to use for cross-sectional features.
        lookback_days: Number of trading days to look back.
        as_of_date: Reference date (defaults to today).
        feature_names: Override feature list (defaults to REGIME_FEATURES).

    Returns:
        Dict with fitting metadata (n_observations, convergence, etc.).
    """
    from astraeus_features.retrieval import get

    if as_of_date is None:
        as_of_date = date.today()

    features_to_use = feature_names or REGIME_FEATURES

    logger.info(
        "regime_fitting_start",
        lookback_days=lookback_days,
        n_symbols=len(symbols),
        n_features=len(features_to_use),
        as_of_date=as_of_date.isoformat(),
    )

    # Build historical feature matrix: feature_name -> list of daily value vectors
    historical_features: dict[str, list[list[float]]] = {f: [] for f in features_to_use}

    # Sample daily observations over the lookback period
    # Use business days approximation (5/7 of calendar days)
    n_samples = min(lookback_days, 756)
    step = max(1, lookback_days // n_samples)

    observations_collected = 0

    for day_offset in range(0, lookback_days, step):
        sample_date = as_of_date - timedelta(days=day_offset)
        as_of_ts = datetime(
            sample_date.year, sample_date.month, sample_date.day, 16, 0, tzinfo=UTC
        )

        try:
            feature_matrix = await get(
                session=session,
                symbols=symbols,
                feature_names=features_to_use,
                as_of_ts=as_of_ts,
            )

            # Extract cross-sectional values for each feature
            for feature_name in features_to_use:
                daily_values = []
                for symbol in symbols:
                    val = feature_matrix.get(symbol, {}).get(feature_name)
                    if val is not None:
                        daily_values.append(val)

                historical_features[feature_name].append(daily_values)

            observations_collected += 1

        except Exception as e:
            logger.debug(
                "regime_fitting_day_skipped",
                date=sample_date.isoformat(),
                error=str(e),
            )
            # Skip days with missing data
            for feature_name in features_to_use:
                historical_features[feature_name].append([])

    # Filter out features with insufficient data
    valid_features: dict[str, list[list[float]]] = {}
    for fname, daily_lists in historical_features.items():
        non_empty = [d for d in daily_lists if len(d) > 0]
        if len(non_empty) >= 50:  # Need at least 50 observations
            valid_features[fname] = daily_lists

    if len(valid_features) < 2:
        logger.warning(
            "regime_fitting_insufficient_features",
            valid_features=list(valid_features.keys()),
            required=2,
        )
        return {
            "status": "insufficient_data",
            "valid_features": list(valid_features.keys()),
            "observations_collected": observations_collected,
        }

    # Fit the detector (HMM + GMM)
    detector.fit(valid_features)

    logger.info(
        "regime_fitting_complete",
        n_features=len(valid_features),
        n_observations=observations_collected,
        features_used=list(valid_features.keys()),
    )

    return {
        "status": "fitted",
        "n_features": len(valid_features),
        "n_observations": observations_collected,
        "features_used": list(valid_features.keys()),
        "as_of_date": as_of_date.isoformat(),
        "lookback_days": lookback_days,
    }


async def fit_from_market_bars(
    session: AsyncSession,
    detector: RegimeDetector,
    symbols: list[str],
    lookback_days: int = 756,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Fit regime models directly from market bars (fallback when features unavailable).

    Computes volatility and momentum directly from adjusted price data.

    Args:
        session: Database session.
        detector: RegimeDetector to fit.
        symbols: Universe symbols.
        lookback_days: Lookback period.
        as_of_date: Reference date.

    Returns:
        Fitting metadata dict.
    """
    from sqlalchemy import text

    if as_of_date is None:
        as_of_date = date.today()

    start_date = as_of_date - timedelta(days=int(lookback_days * 1.5))  # Calendar days buffer

    logger.info(
        "regime_fitting_from_bars_start",
        n_symbols=len(symbols),
        start_date=start_date.isoformat(),
        as_of_date=as_of_date.isoformat(),
    )

    # Query adjusted close prices for the universe
    query = text("""
        SELECT symbol, ts::date as trade_date, close
        FROM market_bars_adjusted
        WHERE symbol = ANY(:symbols)
          AND resolution = '1d'
          AND ts >= :start_date
          AND ts <= :end_date
        ORDER BY ts
    """)

    result = await session.execute(
        query,
        {"symbols": symbols, "start_date": start_date, "end_date": as_of_date},
    )
    rows = result.all()

    if len(rows) < 100:
        return {"status": "insufficient_data", "rows": len(rows)}

    # Organize by date
    from collections import defaultdict

    daily_prices: dict[date, dict[str, float]] = defaultdict(dict)
    for row in rows:
        daily_prices[row[1]][row[0]] = float(row[2])

    sorted_dates = sorted(daily_prices.keys())

    # Compute daily features: cross-sectional volatility and average return
    vol_series: list[list[float]] = []
    ret_series: list[list[float]] = []

    window = 20
    for i in range(window, len(sorted_dates)):
        window_dates = sorted_dates[i - window : i]

        daily_vols = []
        daily_rets = []

        for symbol in symbols:
            prices = []
            for d in window_dates:
                p = daily_prices[d].get(symbol)
                if p is not None and p > 0:
                    prices.append(p)

            if len(prices) >= window // 2:
                # Compute log returns
                log_rets = [
                    np.log(prices[j] / prices[j - 1])
                    for j in range(1, len(prices))
                    if prices[j - 1] > 0
                ]
                if log_rets:
                    daily_vols.append(float(np.std(log_rets) * np.sqrt(252)))
                    daily_rets.append(float(np.mean(log_rets) * 252))

        vol_series.append(daily_vols)
        ret_series.append(daily_rets)

    historical_features = {
        "realized_vol_20d": vol_series,
        "annualized_return_20d": ret_series,
    }

    # Fit
    detector.fit(historical_features)

    logger.info(
        "regime_fitting_from_bars_complete",
        n_observations=len(vol_series),
        n_dates=len(sorted_dates),
    )

    return {
        "status": "fitted",
        "method": "market_bars",
        "n_observations": len(vol_series),
        "n_dates": len(sorted_dates),
        "as_of_date": as_of_date.isoformat(),
    }
