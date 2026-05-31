"""Signal decay tracking.

Monitors each signal's rolling performance (Sharpe, hit rate) and
automatically down-weights signals that have stopped working.

This is where most retail systems quietly die — they keep using a
momentum signal that stopped working in 2022.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date

import numpy as np
import structlog

logger = structlog.get_logger("astraeus.ensemble.decay")


@dataclass
class SignalPerformanceEntry:
    """Daily performance observation for a signal."""

    run_date: date
    pnl: float  # Daily PnL contribution from this signal
    hit: bool  # Whether the signal's direction was correct


@dataclass
class SignalHealth:
    """Current health metrics for a signal."""

    signal_name: str
    rolling_sharpe: float = 0.0
    rolling_hit_rate: float = 0.5
    decay_factor: float = 1.0  # 1.0 = healthy, 0.0 = fully decayed
    days_tracked: int = 0
    last_updated: date | None = None


class DecayTracker:
    """Tracks signal health and computes decay factors.

    Each signal has a rolling Sharpe and hit rate. When the trailing
    window underperforms, the signal's weight decays toward zero.
    """

    def __init__(
        self,
        window_days: int = 90,
        sharpe_floor: float = 0.3,
        hit_rate_floor: float = 0.45,
        decay_rate: float = 0.5,
    ) -> None:
        """Initialize the decay tracker.

        Args:
            window_days: Rolling window for performance calculation.
            sharpe_floor: Sharpe below this triggers decay.
            hit_rate_floor: Hit rate below this triggers decay.
            decay_rate: How much to decay (0.5 = halve the weight).
        """
        self._window = window_days
        self._sharpe_floor = sharpe_floor
        self._hit_rate_floor = hit_rate_floor
        self._decay_rate = decay_rate
        self._history: dict[str, deque[SignalPerformanceEntry]] = {}
        self._health: dict[str, SignalHealth] = {}

    def record(self, signal_name: str, run_date: date, pnl: float, hit: bool) -> None:
        """Record a daily performance observation for a signal.

        Args:
            signal_name: Canonical signal name.
            run_date: Date of observation.
            pnl: PnL contribution from this signal.
            hit: Whether the signal's direction was correct.
        """
        if signal_name not in self._history:
            self._history[signal_name] = deque(maxlen=self._window)
            self._health[signal_name] = SignalHealth(signal_name=signal_name)

        entry = SignalPerformanceEntry(run_date=run_date, pnl=pnl, hit=hit)
        self._history[signal_name].append(entry)

        # Recompute health
        self._update_health(signal_name, run_date)

    def get_decay_factor(self, signal_name: str) -> float:
        """Get the current decay factor for a signal.

        Returns:
            Factor in [0, 1]. Multiply signal weight by this.
        """
        health = self._health.get(signal_name)
        if health is None:
            return 1.0  # Unknown signal — no decay
        return health.decay_factor

    def get_health(self, signal_name: str) -> SignalHealth | None:
        """Get full health metrics for a signal."""
        return self._health.get(signal_name)

    def get_all_health(self) -> dict[str, SignalHealth]:
        """Get health metrics for all tracked signals."""
        return dict(self._health)

    def _update_health(self, signal_name: str, run_date: date) -> None:
        """Recompute health metrics from the rolling window."""
        history = self._history[signal_name]
        health = self._health[signal_name]

        if len(history) < 10:
            # Not enough data — keep healthy
            health.days_tracked = len(history)
            health.last_updated = run_date
            return

        # Compute rolling Sharpe
        pnls = [e.pnl for e in history]
        mean_pnl = np.mean(pnls)
        std_pnl = np.std(pnls, ddof=1)
        if std_pnl > 1e-10:
            health.rolling_sharpe = float(mean_pnl / std_pnl * np.sqrt(252))
        elif mean_pnl > 0:
            # Zero volatility with positive mean → infinitely good Sharpe
            health.rolling_sharpe = float("inf")
        else:
            health.rolling_sharpe = 0.0

        # Compute hit rate
        hits = sum(1 for e in history if e.hit)
        health.rolling_hit_rate = hits / len(history)

        # Compute decay factor
        sharpe_ok = health.rolling_sharpe >= self._sharpe_floor
        hit_rate_ok = health.rolling_hit_rate >= self._hit_rate_floor

        if sharpe_ok and hit_rate_ok:
            # Healthy — restore toward 1.0
            health.decay_factor = min(1.0, health.decay_factor + 0.05)
        elif not sharpe_ok and not hit_rate_ok:
            # Both failing — aggressive decay
            health.decay_factor *= self._decay_rate
        else:
            # One failing — moderate decay
            health.decay_factor *= 1.0 - self._decay_rate * 0.5

        # Floor at a small positive value (never fully zero — allows recovery)
        health.decay_factor = max(0.05, health.decay_factor)

        health.days_tracked = len(history)
        health.last_updated = run_date

        if health.decay_factor < 0.5:
            logger.warning(
                "signal_decaying",
                signal=signal_name,
                decay_factor=round(health.decay_factor, 3),
                rolling_sharpe=round(health.rolling_sharpe, 3),
                hit_rate=round(health.rolling_hit_rate, 3),
            )
