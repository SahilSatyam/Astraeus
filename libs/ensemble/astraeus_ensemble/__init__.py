"""Regime-conditional signal ensemble with correlation penalty and decay tracking.

The ensemble combines multiple signal sources using weights that vary by market regime,
penalizes correlated signals, and tracks signal decay over time.
"""

from .engine import EnsembleEngine

__all__ = ["EnsembleEngine"]
