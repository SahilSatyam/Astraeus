"""Feature definitions — the canonical set of factors for Phase 2 exit criteria.

Each module defines one or more FeatureDefinition instances using the DSL.
These are the 5 factor exposures required by the exit notebook:
- momentum_12_1: 12-1 month price momentum
- value_book_to_market: Book-to-market ratio
- quality_roe: Return on equity (TTM)
- low_vol_60d: 60-day realized volatility (sign-flipped)
- size_log_mcap: Log market cap (sign-flipped)
"""

from astraeus_features.definitions.factors import (
    low_vol_60d,
    momentum_12_1,
    quality_roe,
    size_log_mcap,
    value_book_to_market,
)

ALL_FACTORS = [
    momentum_12_1,
    value_book_to_market,
    quality_roe,
    low_vol_60d,
    size_log_mcap,
]

__all__ = [
    "ALL_FACTORS",
    "low_vol_60d",
    "momentum_12_1",
    "quality_roe",
    "size_log_mcap",
    "value_book_to_market",
]
