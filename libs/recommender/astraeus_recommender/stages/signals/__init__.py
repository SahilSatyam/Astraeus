"""Signal generators — each produces raw scores for the universe.

Hard rule: signals never see ranks. Stage 3 outputs raw scores; Stage 4 ranks.
"""

from .base import SignalGenerator
from .macro import MacroSignal
from .ml_xgb import MLXGBSignal
from .nlp_sentiment import NLPSentimentSignal
from .statistical import StatisticalSignal
from .technical import TechnicalSignal

__all__ = [
    "MLXGBSignal",
    "MacroSignal",
    "NLPSentimentSignal",
    "SignalGenerator",
    "StatisticalSignal",
    "TechnicalSignal",
]
