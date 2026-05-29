"""FinBERT sentiment analysis wrapper.

Wraps the ProsusAI/finbert model from HuggingFace for financial sentiment.
Deterministic, fast on CPU, battle-tested in literature.

Output: (label, score) where:
- label: "positive", "negative", "neutral"
- score: float in [-1, 1] (negative = -1, neutral = 0, positive = 1)

The model is loaded lazily and cached. Pin the model version for reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger("astraeus.nlp.sentiment")

# Model identifier — pinned for reproducibility
FINBERT_MODEL = "ProsusAI/finbert"
FINBERT_VERSION = "v1.0"


@dataclass(frozen=True, slots=True)
class SentimentResult:
    """Sentiment analysis result for a single text."""

    label: str  # "positive", "negative", "neutral"
    score: float  # [-1, 1]
    probabilities: dict[str, float]  # raw softmax outputs


class FinBERTSentiment:
    """FinBERT-based financial sentiment analyzer.

    Lazy-loads the model on first use. Supports both single-text and
    batch inference. CPU-only by default; GPU if available.
    """

    def __init__(
        self,
        model_name: str = FINBERT_MODEL,
        device: str | None = None,
        max_length: int = 512,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._max_length = max_length
        self._pipeline = None

    def _load_pipeline(self) -> object:
        """Lazy-load the HuggingFace pipeline."""
        if self._pipeline is None:
            from transformers import pipeline

            device_arg = self._device
            if device_arg is None:
                import torch

                device_arg = "cuda" if torch.cuda.is_available() else "cpu"

            logger.info(
                "finbert_loading",
                model=self._model_name,
                device=device_arg,
            )

            self._pipeline = pipeline(
                "text-classification",
                model=self._model_name,
                tokenizer=self._model_name,
                device=device_arg if device_arg != "cpu" else -1,
                max_length=self._max_length,
                truncation=True,
                top_k=None,  # Return all class probabilities
            )

            logger.info("finbert_loaded")

        return self._pipeline

    def analyze(self, text: str) -> SentimentResult:
        """Analyze sentiment of a single text.

        Returns a SentimentResult with the dominant label and a normalized
        score in [-1, 1].
        """
        if not text.strip():
            return SentimentResult(label="neutral", score=0.0, probabilities={})

        pipe = self._load_pipeline()
        outputs = pipe(text[: self._max_length * 4])  # rough char limit

        # Parse pipeline output
        probs = {}
        if isinstance(outputs, list) and outputs:
            # top_k=None returns list of dicts per input
            results = outputs[0] if isinstance(outputs[0], list) else outputs
            for item in results:
                probs[item["label"].lower()] = item["score"]

        # Compute normalized score: positive - negative
        pos = probs.get("positive", 0.0)
        neg = probs.get("negative", 0.0)
        score = pos - neg  # Range: [-1, 1]

        # Determine dominant label
        label = max(probs, key=probs.get, default="neutral")  # type: ignore[arg-type]

        return SentimentResult(label=label, score=score, probabilities=probs)

    def analyze_batch(self, texts: list[str]) -> list[SentimentResult]:
        """Batch sentiment analysis for efficiency.

        Uses HuggingFace pipeline batching for throughput.
        """
        if not texts:
            return []

        pipe = self._load_pipeline()

        # Filter empty texts
        valid_texts = [t[: self._max_length * 4] for t in texts if t.strip()]
        if not valid_texts:
            return [SentimentResult(label="neutral", score=0.0, probabilities={}) for _ in texts]

        outputs = pipe(valid_texts, batch_size=16)

        results: list[SentimentResult] = []
        output_idx = 0

        for text in texts:
            if not text.strip():
                results.append(SentimentResult(label="neutral", score=0.0, probabilities={}))
                continue

            raw = outputs[output_idx]
            output_idx += 1

            probs = {}
            items = raw if isinstance(raw, list) else [raw]
            for item in items:
                probs[item["label"].lower()] = item["score"]

            pos = probs.get("positive", 0.0)
            neg = probs.get("negative", 0.0)
            score = pos - neg
            label = max(probs, key=probs.get, default="neutral")  # type: ignore[arg-type]

            results.append(SentimentResult(label=label, score=score, probabilities=probs))

        return results
