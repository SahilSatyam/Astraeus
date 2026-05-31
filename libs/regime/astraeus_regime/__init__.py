"""Market regime detection via HMM and GMM with stability filtering.

Provides temporal (HMM) and cross-sectional (GMM) regime classification
with a stability filter that prevents regime flip-flopping.
"""

from .detector import RegimeDetector, RegimeResult

__all__ = ["RegimeDetector", "RegimeResult"]
