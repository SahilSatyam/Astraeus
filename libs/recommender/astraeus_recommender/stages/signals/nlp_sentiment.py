"""NLP Sentiment signal generator.

Produces sentiment scores from the NLP pipeline (Phase 5 alt-data).
Aggregates recent news/social sentiment into a daily signal.
"""

from __future__ import annotations

from ...contracts import DailyInputSnapshot, SignalName, SignalValue
from .base import SignalGenerator


class NLPSentimentSignal(SignalGenerator):
    """NLP-based sentiment signal from news and social media."""

    @property
    def name(self) -> SignalName:
        return SignalName.NLP_SENTIMENT

    async def generate(self, snapshot: DailyInputSnapshot) -> list[SignalValue]:
        """Generate sentiment scores from NLP features."""
        values: list[SignalValue] = []

        for symbol in snapshot.symbols:
            features = snapshot.feature_matrix.get(symbol, {})

            # Sentiment features from the alt-data pipeline
            news_sentiment = features.get("news_sentiment_3d")
            social_sentiment = features.get("social_sentiment_1d")
            sentiment_momentum = features.get("sentiment_momentum_7d")
            news_volume = features.get("news_volume_zscore")

            if news_sentiment is None and social_sentiment is None:
                continue

            score = 0.0
            weight_sum = 0.0

            if news_sentiment is not None:
                score += 0.4 * news_sentiment
                weight_sum += 0.4

            if social_sentiment is not None:
                score += 0.25 * social_sentiment
                weight_sum += 0.25

            if sentiment_momentum is not None:
                # Accelerating sentiment is a stronger signal
                score += 0.2 * sentiment_momentum
                weight_sum += 0.2

            if news_volume is not None:
                # High news volume amplifies the signal direction
                amplifier = min(abs(news_volume), 2.0) / 2.0
                if weight_sum > 0:
                    score *= 1.0 + 0.15 * amplifier
                weight_sum += 0.15

            if weight_sum > 0:
                score /= weight_sum

            confidence = weight_sum / 1.0

            values.append(
                SignalValue(ticker=symbol, score=score, confidence=confidence)
            )

        return values
