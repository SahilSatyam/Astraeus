"""Unit tests for the hybrid RAG retriever.

Tests RRF fusion logic, filter construction, and result ranking
without requiring a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from astraeus_rag.retriever import HybridRetriever, RetrievalFilter, RetrievedChunk


class TestRRFFusion:
    """Test Reciprocal Rank Fusion logic."""

    def _make_chunk(
        self,
        chunk_id: uuid.UUID | None = None,
        text: str = "test chunk",
        score: float = 0.5,
        bm25_rank: int | None = None,
        vector_rank: int | None = None,
    ) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=chunk_id or uuid.uuid4(),
            doc_id=uuid.uuid4(),
            text=text,
            score=score,
            bm25_rank=bm25_rank,
            vector_rank=vector_rank,
            source="rss",
            title="Test",
            publish_ts=datetime(2024, 6, 1, tzinfo=UTC),
        )

    def test_rrf_fuse_empty_lists(self) -> None:
        """RRF with empty inputs returns empty."""
        retriever = HybridRetriever(session=None)  # type: ignore[arg-type]
        result = retriever._rrf_fuse([], [], k=10)
        assert result == []

    def test_rrf_fuse_single_list(self) -> None:
        """RRF with one empty list returns items from the other."""
        retriever = HybridRetriever(session=None)  # type: ignore[arg-type]
        chunk = self._make_chunk(bm25_rank=0)
        result = retriever._rrf_fuse([chunk], [], k=10)
        assert len(result) == 1
        assert result[0].chunk_id == chunk.chunk_id

    def test_rrf_fuse_overlap_boosts_score(self) -> None:
        """Chunks appearing in both lists get higher RRF scores."""
        retriever = HybridRetriever(session=None)  # type: ignore[arg-type]
        shared_id = uuid.uuid4()
        other_id = uuid.uuid4()

        bm25_results = [
            self._make_chunk(chunk_id=shared_id, bm25_rank=0),
            self._make_chunk(chunk_id=other_id, bm25_rank=1),
        ]
        vector_results = [
            self._make_chunk(chunk_id=shared_id, vector_rank=0),
        ]

        result = retriever._rrf_fuse(bm25_results, vector_results, k=10)

        # Shared chunk should be ranked first (appears in both lists)
        assert result[0].chunk_id == shared_id
        assert result[0].bm25_rank == 0
        assert result[0].vector_rank == 0

    def test_rrf_fuse_respects_k_limit(self) -> None:
        """RRF returns at most k results."""
        retriever = HybridRetriever(session=None)  # type: ignore[arg-type]
        bm25_results = [self._make_chunk(bm25_rank=i) for i in range(20)]
        vector_results = [self._make_chunk(vector_rank=i) for i in range(20)]

        result = retriever._rrf_fuse(bm25_results, vector_results, k=5)
        assert len(result) == 5

    def test_rrf_fuse_scores_decrease(self) -> None:
        """RRF results are sorted by decreasing score."""
        retriever = HybridRetriever(session=None)  # type: ignore[arg-type]
        bm25_results = [self._make_chunk(bm25_rank=i) for i in range(10)]
        vector_results = [self._make_chunk(vector_rank=i) for i in range(10)]

        result = retriever._rrf_fuse(bm25_results, vector_results, k=10)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_rrf_custom_k_constant(self) -> None:
        """Custom RRF k constant changes score magnitudes."""
        retriever_low_k = HybridRetriever(session=None, rrf_k=10)  # type: ignore[arg-type]
        retriever_high_k = HybridRetriever(session=None, rrf_k=100)  # type: ignore[arg-type]

        chunk_id = uuid.uuid4()
        bm25 = [self._make_chunk(chunk_id=chunk_id, bm25_rank=0)]
        vector = [self._make_chunk(chunk_id=chunk_id, vector_rank=0)]

        result_low = retriever_low_k._rrf_fuse(bm25, vector, k=1)
        result_high = retriever_high_k._rrf_fuse(bm25, vector, k=1)

        # Lower k gives higher scores (1/(k+rank) is larger when k is smaller)
        assert result_low[0].score > result_high[0].score


class TestRetrievalFilter:
    """Test RetrievalFilter dataclass."""

    def test_default_filter_all_none(self) -> None:
        f = RetrievalFilter()
        assert f.ticker is None
        assert f.sources is None
        assert f.as_of is None

    def test_filter_with_values(self) -> None:
        now = datetime(2024, 12, 15, tzinfo=UTC)
        f = RetrievalFilter(ticker="AAPL", sources=["edgar", "rss"], as_of=now)
        assert f.ticker == "AAPL"
        assert f.sources == ["edgar", "rss"]
        assert f.as_of == now


class TestRetrievedChunk:
    """Test RetrievedChunk dataclass."""

    def test_chunk_fields(self) -> None:
        cid = uuid.uuid4()
        did = uuid.uuid4()
        now = datetime(2024, 6, 1, tzinfo=UTC)

        chunk = RetrievedChunk(
            chunk_id=cid,
            doc_id=did,
            text="Apple reported strong services growth.",
            score=0.85,
            bm25_rank=2,
            vector_rank=1,
            source="edgar",
            title="AAPL 10-K",
            publish_ts=now,
        )

        assert chunk.chunk_id == cid
        assert chunk.doc_id == did
        assert chunk.score == 0.85
        assert chunk.bm25_rank == 2
        assert chunk.vector_rank == 1
        assert chunk.source == "edgar"
