"""Walk-forward optimization harness.

Supports:
- Anchored (expanding window): train grows over time, OOS slides
- Rolling (fixed window): train slides at fixed length
- Purge + embargo between train/val and val/OOS (López de Prado 2018, Ch. 7)
- Purged k-fold cross-validation for ML strategies

Default split: 70% train, 15% val, 15% OOS.
Purge >= max(feature_horizon, label_horizon); embargo = 1% of train length, min 5 days.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import structlog

from astraeus_strategy.metrics import BacktestMetrics

logger = structlog.get_logger("astraeus.strategy.walk_forward")


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    """A single train/val/OOS window."""

    train_start: date
    train_end: date
    val_start: date
    val_end: date
    oos_start: date
    oos_end: date
    fold_index: int = 0


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    """Configuration for walk-forward analysis."""

    mode: str = "anchored"  # 'anchored' or 'rolling'
    train_pct: float = 0.70
    val_pct: float = 0.15
    oos_pct: float = 0.15
    purge_days: int = 5  # gap between train/val
    embargo_days: int = 5  # gap between val/OOS
    min_train_days: int = 252  # minimum 1 year of training
    step_days: int = 63  # step forward by ~1 quarter


@dataclass(slots=True)
class WalkForwardResult:
    """Results from a walk-forward analysis."""

    windows: list[WalkForwardWindow] = field(default_factory=list)
    train_metrics: list[BacktestMetrics] = field(default_factory=list)
    val_metrics: list[BacktestMetrics] = field(default_factory=list)
    oos_metrics: list[BacktestMetrics] = field(default_factory=list)
    best_params_per_window: list[dict[str, Any]] = field(default_factory=list)

    @property
    def avg_oos_sharpe(self) -> float:
        if not self.oos_metrics:
            return 0.0
        return float(np.mean([m.sharpe for m in self.oos_metrics]))

    @property
    def avg_oos_return(self) -> float:
        if not self.oos_metrics:
            return 0.0
        return float(np.mean([m.annualized_return for m in self.oos_metrics]))

    @property
    def worst_oos_drawdown(self) -> float:
        if not self.oos_metrics:
            return 0.0
        return float(min(m.max_drawdown for m in self.oos_metrics))


def generate_windows(
    start: date,
    end: date,
    config: WalkForwardConfig,
) -> list[WalkForwardWindow]:
    """Generate walk-forward windows for the given date range.

    Args:
        start: First available data date.
        end: Last available data date.
        config: Walk-forward configuration.

    Returns:
        List of WalkForwardWindow objects.
    """
    total_days = (end - start).days
    if total_days < config.min_train_days + 60:
        logger.warning("insufficient_data_for_walk_forward", total_days=total_days)
        return []

    windows: list[WalkForwardWindow] = []
    fold_index = 0

    if config.mode == "anchored":
        # Anchored: train always starts at `start`, grows over time
        train_start = start
        current_train_end = start + timedelta(days=config.min_train_days)

        while True:
            # Compute window boundaries
            remaining = (end - current_train_end).days
            val_days = max(int(remaining * config.val_pct / (config.val_pct + config.oos_pct)), 21)
            oos_days = max(remaining - val_days - config.purge_days - config.embargo_days, 21)

            if oos_days < 21:
                break

            val_start = current_train_end + timedelta(days=config.purge_days)
            val_end = val_start + timedelta(days=val_days)
            oos_start = val_end + timedelta(days=config.embargo_days)
            oos_end = min(oos_start + timedelta(days=oos_days), end)

            if oos_end <= oos_start:
                break

            windows.append(WalkForwardWindow(
                train_start=train_start,
                train_end=current_train_end,
                val_start=val_start,
                val_end=val_end,
                oos_start=oos_start,
                oos_end=oos_end,
                fold_index=fold_index,
            ))

            fold_index += 1
            current_train_end += timedelta(days=config.step_days)

            if current_train_end >= end - timedelta(days=60):
                break

    elif config.mode == "rolling":
        # Rolling: fixed-length train window slides forward
        train_days = int(total_days * config.train_pct)
        val_days = int(total_days * config.val_pct)
        oos_days = int(total_days * config.oos_pct)

        current_start = start

        while True:
            train_end = current_start + timedelta(days=train_days)
            val_start = train_end + timedelta(days=config.purge_days)
            val_end = val_start + timedelta(days=val_days)
            oos_start = val_end + timedelta(days=config.embargo_days)
            oos_end = oos_start + timedelta(days=oos_days)

            if oos_end > end:
                break

            windows.append(WalkForwardWindow(
                train_start=current_start,
                train_end=train_end,
                val_start=val_start,
                val_end=val_end,
                oos_start=oos_start,
                oos_end=oos_end,
                fold_index=fold_index,
            ))

            fold_index += 1
            current_start += timedelta(days=config.step_days)

    logger.info("walk_forward_windows_generated", count=len(windows), mode=config.mode)
    return windows


def purged_kfold_splits(
    n_samples: int,
    n_splits: int = 5,
    purge: int = 5,
    embargo: int = 5,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Generate purged k-fold cross-validation splits.

    Implements López de Prado's purged k-fold (Advances in Financial ML, Ch. 7):
    - Removes `purge` samples before each test fold
    - Removes `embargo` samples after each test fold
    - Prevents information leakage from overlapping labels

    Args:
        n_samples: Total number of samples.
        n_splits: Number of folds.
        purge: Number of samples to purge before test fold.
        embargo: Number of samples to embargo after test fold.

    Returns:
        List of (train_indices, test_indices) tuples.
    """
    indices = np.arange(n_samples)
    fold_size = n_samples // n_splits
    splits: list[tuple[np.ndarray, np.ndarray]] = []

    for i in range(n_splits):
        test_start = i * fold_size
        test_end = min((i + 1) * fold_size, n_samples)

        test_indices = indices[test_start:test_end]

        # Purge: remove samples just before test
        purge_start = max(0, test_start - purge)
        # Embargo: remove samples just after test
        embargo_end = min(n_samples, test_end + embargo)

        # Train = everything except test + purge + embargo
        train_mask = np.ones(n_samples, dtype=bool)
        train_mask[purge_start:embargo_end] = False
        train_indices = indices[train_mask]

        splits.append((train_indices, test_indices))

    return splits
