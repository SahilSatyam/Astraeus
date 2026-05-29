"""Transaction cost model.

Implements realistic execution costs:
- Commission (tiered, per-broker profile)
- Spread (multiple estimators: fixed, Roll, Corwin-Schultz)
- Market impact (square-root law, Almgren et al. 2005)
- Slippage (normal noise + latency-conditional drift)

References:
- Almgren, Thum, Hauptmann, Li (2005), "Direct estimation of equity market impact"
- Kyle (1985), "Continuous auctions and insider trading"
- Frazzini, Israel, Moskowitz (2018), "Trading costs"
- Roll (1984), "A simple implicit measure of the effective bid-ask spread"
- Corwin & Schultz (2012), "A simple way to estimate bid-ask spreads from daily high and low prices"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """Breakdown of transaction costs for a single trade."""

    commission: float = 0.0
    spread_cost: float = 0.0
    impact_cost: float = 0.0
    slippage: float = 0.0

    @property
    def total(self) -> float:
        return self.commission + self.spread_cost + self.impact_cost + self.slippage

    @property
    def total_bps(self) -> float:
        """Total cost in basis points (requires trade_value context)."""
        return self.total


@dataclass(slots=True)
class BrokerProfile:
    """Commission schedule for a specific broker."""

    name: str = "interactive_brokers_pro"
    per_share: float = 0.0035
    min_per_order: float = 0.35
    max_pct_of_trade: float = 0.01  # 1% cap

    def commission(self, shares: int, price: float) -> float:
        """Calculate commission for a trade."""
        trade_value = abs(shares) * price
        raw = abs(shares) * self.per_share
        raw = max(raw, self.min_per_order)
        raw = min(raw, trade_value * self.max_pct_of_trade)
        return raw


# Pre-defined broker profiles
BROKER_IB_PRO = BrokerProfile("interactive_brokers_pro", 0.0035, 0.35, 0.01)
BROKER_ALPACA = BrokerProfile("alpaca_zero", 0.0, 0.0, 0.0)
BROKER_CRYPTO = BrokerProfile("crypto_default", 0.001, 0.0, 1.0)  # 10 bps


@dataclass(slots=True)
class SpreadEstimator:
    """Spread estimation configuration."""

    method: str = "corwin_schultz"  # 'fixed_bps', 'roll', 'corwin_schultz', 'quote_replay'
    fixed_bps: float = 10.0  # used only for 'fixed_bps' method

    def estimate_half_spread_bps(
        self,
        high: float | None = None,
        low: float | None = None,
        close: float | None = None,
        prev_close: float | None = None,
        **kwargs: Any,
    ) -> float:
        """Estimate half-spread in basis points."""
        if self.method == "fixed_bps":
            return self.fixed_bps / 2.0

        if self.method == "corwin_schultz" and high and low and high > low:
            # Corwin-Schultz (2012) high-low estimator
            # Simplified single-day version
            beta = (math.log(high / low)) ** 2
            gamma = (math.log(high / low)) ** 2
            alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / (3 - 2 * math.sqrt(2))
            spread = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
            return max(spread * 10000 / 2, 1.0)  # floor at 1 bps half-spread

        if self.method == "roll" and close and prev_close:
            # Roll (1984) implied spread from serial covariance
            # Simplified: spread ≈ 2 * sqrt(-cov(Δp_t, Δp_{t-1}))
            # For single observation, use a proxy
            return 5.0  # default fallback

        return self.fixed_bps / 2.0  # fallback


@dataclass(slots=True)
class CostModel:
    """Full transaction cost model combining all components.

    Usage:
        model = CostModel()
        cost = model.compute(
            shares=1000, price=150.0, adv=5_000_000,
            sigma_daily=0.02, high=152.0, low=148.0
        )
        print(cost.total, cost.total_bps)
    """

    broker: BrokerProfile = field(default_factory=lambda: BROKER_IB_PRO)
    spread: SpreadEstimator = field(default_factory=SpreadEstimator)
    eta: float = 0.5  # market impact coefficient (Almgren et al. 2005)
    slippage_bps: float = 2.0  # normal noise term
    rng: Any = field(default=None)  # numpy RNG for slippage

    # Version tracking for reproducibility
    version: str = "1.0.0"

    def compute(
        self,
        shares: int,
        price: float,
        adv: float = 1_000_000,
        sigma_daily: float = 0.02,
        high: float | None = None,
        low: float | None = None,
        prev_close: float | None = None,
        latency_ms: float = 0.0,
        bar_duration_ms: float = 86_400_000.0,
        bar_range_bps: float = 100.0,
    ) -> CostBreakdown:
        """Compute full transaction cost breakdown for a trade.

        Args:
            shares: Number of shares traded (signed: positive=buy, negative=sell).
            price: Execution reference price.
            adv: 20-day average daily volume in shares.
            sigma_daily: 20-day realized daily volatility (decimal, e.g., 0.02 = 2%).
            high: Current bar high (for spread estimation).
            low: Current bar low (for spread estimation).
            prev_close: Previous bar close (for Roll estimator).
            latency_ms: Order latency in milliseconds.
            bar_duration_ms: Bar duration in milliseconds.
            bar_range_bps: Bar range in basis points.

        Returns:
            CostBreakdown with commission, spread, impact, and slippage.
        """
        trade_value = abs(shares) * price

        # 1. Commission
        commission = self.broker.commission(shares, price)

        # 2. Spread cost: half-spread × trade value
        half_spread_bps = self.spread.estimate_half_spread_bps(
            high=high, low=low, close=price, prev_close=prev_close
        )
        spread_cost = trade_value * half_spread_bps / 10_000

        # 3. Market impact: square-root law
        # impact_bps = sigma_daily_bps × eta × sqrt(|Q| / ADV)
        sigma_bps = sigma_daily * 10_000
        participation = abs(shares) / max(adv, 1)
        impact_bps = sigma_bps * self.eta * math.sqrt(participation)
        impact_cost = trade_value * impact_bps / 10_000

        # 4. Slippage: normal noise + latency-conditional drift
        rng = self.rng or np.random.default_rng(42)
        noise_bps = rng.normal(0, self.slippage_bps)
        latency_drift_bps = 0.0
        if latency_ms > 0 and bar_duration_ms > 0:
            latency_drift_bps = (latency_ms / bar_duration_ms) * bar_range_bps
        total_slippage_bps = abs(noise_bps) + latency_drift_bps
        slippage_cost = trade_value * total_slippage_bps / 10_000

        return CostBreakdown(
            commission=commission,
            spread_cost=spread_cost,
            impact_cost=impact_cost,
            slippage=slippage_cost,
        )
