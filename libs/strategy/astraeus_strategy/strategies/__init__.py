"""Reference strategies — the five archetypes for Phase 3 exit criteria."""

from astraeus_strategy.strategies.factor_blend import FactorBlend
from astraeus_strategy.strategies.mean_reversion import MeanReversion5D
from astraeus_strategy.strategies.ml_forecast import MLForecast
from astraeus_strategy.strategies.momentum import Momentum12_1
from astraeus_strategy.strategies.pairs import PairsTrading

__all__ = [
    "FactorBlend",
    "MLForecast",
    "MeanReversion5D",
    "Momentum12_1",
    "PairsTrading",
]
