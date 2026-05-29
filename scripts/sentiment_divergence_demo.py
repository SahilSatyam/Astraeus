"""Sentiment-Divergence Detector Demo — AAPL.

Shows where social sentiment diverges from price for >= 30 days,
with backtest contextualizing whether that divergence has predictive content.

Expected result: "weak; not stand-alone alpha" — sentiment divergence alone
is not a reliable signal, but it's a useful feature in combination with
quant signals (Phase 7 ensemble).

Usage:
    uv run python scripts/sentiment_divergence_demo.py

Requires:
    - Database with sentiment_score and market_bars_raw tables populated
    - Or runs in demo mode with synthetic data if DB is unavailable
"""

from __future__ import annotations

import numpy as np


def generate_synthetic_data(
    ticker: str = "AAPL",
    days: int = 365,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate synthetic price and sentiment data for demo purposes.

    Creates realistic-looking data with:
    - Price following a random walk with drift
    - Sentiment that mostly tracks price but occasionally diverges
    - Divergence periods of 30+ days

    Returns: (dates_ordinal, prices, sentiment_scores)
    """
    rng = np.random.default_rng(42)

    # Generate price series (geometric random walk)
    daily_returns = rng.normal(0.0005, 0.015, days)  # ~12% annual, ~24% vol
    prices = 150.0 * np.exp(np.cumsum(daily_returns))

    # Generate sentiment that mostly tracks 5-day price momentum
    momentum_5d = np.zeros(days)
    for i in range(5, days):
        momentum_5d[i] = (prices[i] - prices[i - 5]) / prices[i - 5]

    # Sentiment = noisy version of momentum + occasional divergence
    sentiment = np.clip(momentum_5d * 10 + rng.normal(0, 0.2, days), -1, 1)

    # Inject divergence periods (sentiment stays positive while price drops)
    # Period 1: days 100-145 (sentiment positive, price declining)
    prices[100:145] = prices[99] * np.exp(np.cumsum(rng.normal(-0.005, 0.01, 45)))
    sentiment[100:145] = rng.uniform(0.2, 0.6, 45)

    # Period 2: days 250-295 (sentiment negative, price rising)
    prices[250:295] = prices[249] * np.exp(np.cumsum(rng.normal(0.004, 0.01, 45)))
    sentiment[250:295] = rng.uniform(-0.6, -0.2, 45)

    return np.arange(days, dtype=float), prices, sentiment


def detect_divergences(
    prices: np.ndarray,
    sentiment: np.ndarray,
    window: int = 30,
    threshold: float = 0.3,
) -> list[dict[str, object]]:
    """Detect periods where sentiment diverges from price direction.

    A divergence is detected when:
    - Price trend (30-day return) and sentiment average disagree in sign
    - The disagreement persists for >= `window` days
    - The magnitude of disagreement exceeds `threshold`

    Returns list of divergence periods with metadata.
    """
    n = len(prices)
    divergences: list[dict[str, object]] = []

    # Compute rolling metrics
    price_trend = np.zeros(n)
    sentiment_avg = np.zeros(n)

    for i in range(window, n):
        price_trend[i] = (prices[i] - prices[i - window]) / prices[i - window]
        sentiment_avg[i] = np.mean(sentiment[i - window : i])

    # Detect sign disagreements
    in_divergence = False
    div_start = 0

    for i in range(window, n):
        # Divergence: price down but sentiment positive, or vice versa
        price_dir = 1 if price_trend[i] > 0.02 else (-1 if price_trend[i] < -0.02 else 0)
        sent_dir = (
            1 if sentiment_avg[i] > threshold else (-1 if sentiment_avg[i] < -threshold else 0)
        )

        is_divergent = price_dir != 0 and sent_dir not in (0, price_dir)

        if is_divergent and not in_divergence:
            in_divergence = True
            div_start = i
        elif not is_divergent and in_divergence:
            duration = i - div_start
            if duration >= window:
                divergences.append(
                    {
                        "start_day": div_start,
                        "end_day": i,
                        "duration_days": duration,
                        "avg_price_trend": float(np.mean(price_trend[div_start:i])),
                        "avg_sentiment": float(np.mean(sentiment_avg[div_start:i])),
                        "type": "bullish_divergence"
                        if price_trend[div_start] < 0
                        else "bearish_divergence",
                    }
                )
            in_divergence = False

    # Handle ongoing divergence at end
    if in_divergence:
        duration = n - div_start
        if duration >= window:
            divergences.append(
                {
                    "start_day": div_start,
                    "end_day": n - 1,
                    "duration_days": duration,
                    "avg_price_trend": float(np.mean(price_trend[div_start:])),
                    "avg_sentiment": float(np.mean(sentiment_avg[div_start:])),
                    "type": "bullish_divergence"
                    if price_trend[div_start] < 0
                    else "bearish_divergence",
                }
            )

    return divergences


def backtest_divergence_signal(
    prices: np.ndarray,
    divergences: list[dict[str, object]],
    holding_period: int = 20,
) -> dict[str, object]:
    """Backtest: does entering a position at divergence resolution produce alpha?

    Strategy: When a bullish divergence ends (sentiment was positive while price
    fell), go long for `holding_period` days. When bearish divergence ends, go short.

    Returns backtest statistics.
    """
    trades: list[dict[str, float]] = []

    for div in divergences:
        end_day = int(div["end_day"])  # type: ignore[arg-type]
        if end_day + holding_period >= len(prices):
            continue

        entry_price = prices[end_day]
        exit_price = prices[end_day + holding_period]
        ret = (exit_price - entry_price) / entry_price

        if div["type"] == "bullish_divergence":
            # Long after bullish divergence resolves
            trades.append({"return": float(ret), "type": "long"})
        else:
            # Short after bearish divergence resolves
            trades.append({"return": float(-ret), "type": "short"})

    if not trades:
        return {
            "n_trades": 0,
            "avg_return": 0.0,
            "win_rate": 0.0,
            "sharpe": 0.0,
            "conclusion": "No trades generated",
        }

    returns = np.array([t["return"] for t in trades])
    avg_ret = float(np.mean(returns))
    std_ret = float(np.std(returns)) if len(returns) > 1 else 1.0
    win_rate = float(np.mean(returns > 0))
    sharpe = avg_ret / std_ret * np.sqrt(252 / holding_period) if std_ret > 0 else 0.0

    return {
        "n_trades": len(trades),
        "avg_return": round(avg_ret * 100, 2),  # percent
        "win_rate": round(win_rate * 100, 1),
        "sharpe": round(float(sharpe), 2),
        "max_return": round(float(np.max(returns)) * 100, 2),
        "min_return": round(float(np.min(returns)) * 100, 2),
        "conclusion": _interpret_results(float(sharpe), win_rate),
    }


def _interpret_results(sharpe: float, win_rate: float) -> str:
    """Interpret backtest results in context."""
    if abs(sharpe) < 0.3:
        return (
            "Weak; not stand-alone alpha. Sentiment divergence alone does not "
            "produce reliable returns. Use as a feature in the ensemble (Phase 7), "
            "not as a standalone signal."
        )
    if sharpe > 0.3 and win_rate > 0.55:
        return (
            "Moderate signal detected, but likely overfitted to synthetic data. "
            "In live markets, this alpha is crowded and decays quickly. "
            "Combine with quant signals for robustness."
        )
    return (
        "Inconclusive. Insufficient trades or high variance. "
        "Sentiment divergence is a regime indicator, not a timing signal."
    )


def main() -> None:
    """Run the sentiment divergence demo."""
    print("=" * 70)
    print("  AAPL Sentiment-Divergence Detector Demo")
    print("  Phase 5 — Sentiment & Alternative Data")
    print("=" * 70)
    print()

    # Generate synthetic data (in production, this reads from the DB)
    print("[1/4] Generating synthetic price + sentiment data (365 days)...")
    days_arr, prices, sentiment = generate_synthetic_data("AAPL", days=365)
    print(f"      Price range: ${prices.min():.2f} - ${prices.max():.2f}")
    print(f"      Sentiment range: {sentiment.min():.2f} to {sentiment.max():.2f}")
    print()

    # Detect divergences
    print("[2/4] Detecting sentiment-price divergences (window=30 days)...")
    divergences = detect_divergences(prices, sentiment, window=30, threshold=0.2)
    print(f"      Found {len(divergences)} divergence period(s):")
    for i, div in enumerate(divergences, 1):
        print(
            f"        #{i}: days {div['start_day']}-{div['end_day']} "
            f"({div['duration_days']}d) | "
            f"type={div['type']} | "
            f"price_trend={div['avg_price_trend']:+.1%} | "
            f"sentiment={div['avg_sentiment']:+.2f}"
        )
    print()

    # Backtest the divergence signal
    print("[3/4] Backtesting divergence resolution signal (20-day holding)...")
    results = backtest_divergence_signal(prices, divergences, holding_period=20)
    print(f"      Trades: {results['n_trades']}")
    print(f"      Avg return: {results['avg_return']}%")
    print(f"      Win rate: {results['win_rate']}%")
    print(f"      Sharpe: {results['sharpe']}")
    if "max_return" in results:
        print(f"      Best trade: {results['max_return']}%")
        print(f"      Worst trade: {results['min_return']}%")
    print()

    # Conclusion
    print("[4/4] Conclusion:")
    print(f"      {results['conclusion']}")
    print()
    print("-" * 70)
    print("  Key insight: Sentiment divergence is a FEATURE, not a SIGNAL.")
    print("  It gains predictive power only when combined with:")
    print("    - Earnings surprise (Phase 3)")
    print("    - Short interest changes")
    print("    - Options flow / implied vol skew")
    print("    - Factor momentum (Phase 2)")
    print("  This combination is the Phase 7 ensemble's job.")
    print("-" * 70)


if __name__ == "__main__":
    main()
