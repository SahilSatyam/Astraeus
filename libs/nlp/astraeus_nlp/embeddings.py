"""Sentence-transformer embeddings for document chunks.

Uses bge-small-en-v1.5 (384-dim) by default — fast on CPU, good quality
for financial text. Embeddings are stored in pgvector for hybrid retrieval.

Deterministic: same text + same model version = same vector.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger("astraeus.nlp.embeddings")

# Default model — 384-dim, fast on CPU
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Embedding result for a single text."""

    vector: list[float]
    model: str
    dim: int


class SentenceEmbedder:
    """Sentence-transformer embedding model.

    Lazy-loads the model on first use. Supports batch encoding for throughput.
    Deterministic with fixed seeds.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        normalize: bool = True,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._normalize = normalize
        self._model = None

    def _load_model(self) -> object:
        """Lazy-load the sentence-transformers model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            device = self._device
            if device is None:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"

            logger.info("embedder_loading", model=self._model_name, device=device)
            self._model = SentenceTransformer(self._model_name, device=device)
            logger.info("embedder_loaded", dim=self._model.get_sentence_embedding_dimension())

        return self._model

    def embed(self, text: str) -> EmbeddingResult:
        """Embed a single text."""
        model = self._load_model()
        vector = model.encode(
            text,
            normalize_embeddings=self._normalize,
            show_progress_bar=False,
        )
        return EmbeddingResult(
            vector=vector.tolist(),
            model=self._model_name,
            dim=len(vector),
        )

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Batch embedding for efficiency.

        Uses sentence-transformers' built-in batching.
        """
        if not texts:
            return []

        model = self._load_model()
        vectors = model.encode(
            texts,
            normalize_embeddings=self._normalize,
            show_progress_bar=False,
            batch_size=64,
        )

        return [
            EmbeddingResult(
                vector=vec.tolist(),
                model=self._model_name,
                dim=len(vec),
            )
            for vec in vectors
        ]

    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        model = self._load_model()
        return model.get_sentence_embedding_dimension()  # type: ignore[union-attr]
