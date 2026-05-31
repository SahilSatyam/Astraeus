"""Cross-encoder reranker — bge-reranker-base on CPU/GPU.

Takes the top-N candidates from hybrid retrieval (BM25 + vector + RRF)
and reranks them using a cross-encoder model for higher precision.

Pipeline:
  RRF top 50 → cross-encoder rerank → top 8 returned to agent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

logger = structlog.get_logger("astraeus.rag.reranker")

# Default reranker model
_DEFAULT_MODEL = "BAAI/bge-reranker-base"


@dataclass(frozen=True, slots=True)
class RerankResult:
    """A single reranked item with its cross-encoder score."""

    index: int  # Original index in the input list
    score: float  # Cross-encoder relevance score
    text: str = ""


class CrossEncoderReranker:
    """Cross-encoder reranker using sentence-transformers CrossEncoder.

    Loads the model lazily on first use. Runs on CPU by default;
    GPU if available and configured.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        device: str | None = None,
        batch_size: int = 16,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._batch_size = batch_size
        self._model: object | None = None

    def _load_model(self) -> object:
        """Lazy-load the cross-encoder model."""
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import CrossEncoder

            device = self._device
            if device is None:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"

            self._model = CrossEncoder(self._model_name, device=device)
            logger.info("reranker_loaded", model=self._model_name, device=device)
            return self._model
        except ImportError:
            logger.warning("reranker_unavailable", reason="sentence-transformers not installed")
            return None

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 8,
    ) -> list[RerankResult]:
        """Rerank documents by cross-encoder relevance to query.

        Args:
            query: The search query.
            documents: List of document texts to rerank.
            top_k: Number of top results to return.

        Returns:
            Top-k RerankResults sorted by score descending.
        """
        if not documents:
            return []

        start = time.perf_counter()
        model = self._load_model()

        if model is None:
            # Fallback: return documents in original order (no reranking)
            return [
                RerankResult(index=i, score=1.0 - i * 0.01, text=doc)
                for i, doc in enumerate(documents[:top_k])
            ]

        # Build query-document pairs
        pairs = [[query, doc] for doc in documents]

        # Score all pairs
        scores = model.predict(pairs, batch_size=self._batch_size)  # type: ignore[union-attr]

        # Build results with scores
        results = [
            RerankResult(index=i, score=float(score), text=documents[i])
            for i, score in enumerate(scores)
        ]

        # Sort by score descending and take top_k
        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:top_k]

        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "rerank_complete",
            query_len=len(query),
            candidates=len(documents),
            top_k=top_k,
            latency_ms=round(latency_ms, 1),
        )

        return results

    def rerank_chunks(
        self,
        query: str,
        chunks: list[dict[str, object]],
        top_k: int = 8,
        text_key: str = "text",
    ) -> list[dict[str, object]]:
        """Rerank chunk dicts by cross-encoder relevance.

        Convenience method that works with the chunk dicts from the retriever.
        Returns the top-k chunks with an added 'rerank_score' field.
        """
        if not chunks:
            return []

        documents = [str(chunk.get(text_key, "")) for chunk in chunks]
        results = self.rerank(query, documents, top_k=top_k)

        reranked = []
        for result in results:
            chunk = dict(chunks[result.index])
            chunk["rerank_score"] = result.score
            reranked.append(chunk)

        return reranked
