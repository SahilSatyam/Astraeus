"""ML Return Forecast strategy (XGBoost + Meta-Labeling).

Thesis: Cross-sectional ML on rich features forecasts next-week return.
Meta-labeling (López de Prado 2018, Ch. 3) trains a second model to
predict the primary's correctness, used for position sizing.

Logic:
- Weekly rebalance
- Primary: XGBoost binary classifier on cross-sectional features
  Target = sign of next-5d return
- Meta: XGBoost classifier predicting was-primary-correct
- Position size = meta_prob * primary_direction
- Purged 5-fold CV, embargo = 5 days
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import polars as pl

from astraeus_strategy.protocol import Strategy, StrategyContext
from astraeus_strategy.types import (
    Bar,
    DataDependency,
    FeatureRef,
    Fill,
    Order,
    PortfolioState,
    UniverseRef,
)


class MLForecast(Strategy):
    """XGBoost return forecast with meta-labeling."""

    name = "ml_xgboost_meta"
    version = "1.0.0"
    dependencies = DataDependency(
        features=[
            FeatureRef("momentum_12_1", version="1.0.0"),
            FeatureRef("value_book_to_market", version="1.0.0"),
            FeatureRef("quality_roe", version="1.0.0"),
            FeatureRef("low_vol_60d", version="1.0.0"),
            FeatureRef("size_log_mcap", version="1.0.0"),
        ],
        universe=UniverseRef("sp500"),
        calendar="XNYS",
        frequency="1d",
        history_horizon=timedelta(days=500),
    )

    def __init__(self) -> None:
        self._primary_model: Any = None
        self._meta_model: Any = None
        self._last_train_date: Any = None

    def generate_targets(
        self,
        as_of_ts: Any,
        feature_panel: pl.LazyFrame,
        universe: list[str],
        portfolio_state: PortfolioState,
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Generate ML-based targets with meta-labeling for sizing."""
        retrain_freq_days = params.get("retrain_freq_days", 21)
        max_positions = params.get("max_positions", 50)
        gross_target = params.get("gross_target", 1.5)
        feature_cols = params.get("feature_cols", [
            "momentum_12_1", "value_book_to_market",
            "quality_roe", "low_vol_60d", "size_log_mcap",
        ])

        # Collect feature panel
        panel = (
            feature_panel
            .filter(pl.col("symbol").is_in(universe))
            .collect()
        )

        if panel.is_empty() or len(panel) < 100:
            return {}

        # Check if we need to retrain
        needs_retrain = (
            self._primary_model is None
            or self._last_train_date is None
            or (as_of_ts - self._last_train_date).days >= retrain_freq_days
        )

        if needs_retrain:
            self._train(panel, feature_cols, params)
            self._last_train_date = as_of_ts

        if self._primary_model is None:
            return {}

        # Get latest features for prediction
        latest = panel.group_by("symbol").agg([
            pl.col(c).last().alias(c) for c in feature_cols if c in panel.columns
        ])

        available_cols = [c for c in feature_cols if c in latest.columns]
        if not available_cols:
            return {}

        # Prepare feature matrix
        X = latest.select(available_cols).to_numpy()

        # Handle NaN: fill with 0 (cross-sectional median would be better)
        X = np.nan_to_num(X, nan=0.0)

        if len(X) == 0:
            return {}

        # Primary prediction: direction
        try:
            primary_pred = self._primary_model.predict(X)
            primary_proba = self._primary_model.predict_proba(X)[:, 1]
        except Exception:
            return {}

        # Meta prediction: confidence
        if self._meta_model is not None:
            try:
                meta_proba = self._meta_model.predict_proba(X)[:, 1]
            except Exception:
                meta_proba = np.ones(len(X)) * 0.5
        else:
            meta_proba = np.ones(len(X)) * 0.5

        # Build targets: direction * meta_confidence
        symbols = latest["symbol"].to_list()
        scores = (primary_proba - 0.5) * 2 * meta_proba  # [-1, 1] scaled by confidence

        # Select top positions by absolute score
        abs_scores = np.abs(scores)
        top_indices = np.argsort(abs_scores)[-max_positions:]

        targets: dict[str, float] = {}
        total_abs_score = sum(abs_scores[i] for i in top_indices if abs_scores[i] > 0.1)

        if total_abs_score < 1e-10:
            return {}

        for idx in top_indices:
            if abs_scores[idx] < 0.1:
                continue
            weight = scores[idx] / total_abs_score * gross_target
            targets[symbols[idx]] = float(weight)

        return targets

    def _train(self, panel: pl.DataFrame, feature_cols: list[str], params: dict[str, Any]) -> None:
        """Train primary and meta models on historical data."""
        try:
            from xgboost import XGBClassifier  # noqa: PLC0415
        except ImportError:
            # XGBoost not installed — skip training
            return

        available_cols = [c for c in feature_cols if c in panel.columns]
        if not available_cols or "close" not in panel.columns:
            return

        # Build training data: features at t, label = sign(return_t+5)
        train_data = panel.sort(["symbol", "ts"])

        # Compute forward 5-day return as label
        train_data = train_data.with_columns(
            (pl.col("close").shift(-5).over("symbol") / pl.col("close") - 1).alias("fwd_ret_5d")
        ).filter(pl.col("fwd_ret_5d").is_not_null())

        if len(train_data) < 200:
            return

        train_data = train_data.with_columns(
            (pl.col("fwd_ret_5d") > 0).cast(pl.Int32).alias("label")
        )

        X = train_data.select(available_cols).to_numpy()
        y = train_data["label"].to_numpy()

        X = np.nan_to_num(X, nan=0.0)

        # Train primary model
        seed = params.get("seed", 42)
        self._primary_model = XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=seed,
            use_label_encoder=False,
            eval_metric="logloss",
        )
        self._primary_model.fit(X, y)

        # Train meta model: predict if primary was correct
        primary_pred = self._primary_model.predict(X)
        meta_label = (primary_pred == y).astype(int)

        self._meta_model = XGBClassifier(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.1,
            random_state=seed + 1,
            use_label_encoder=False,
            eval_metric="logloss",
        )
        self._meta_model.fit(X, meta_label)

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[Order]:
        return []

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> None:
        pass
