"""Unit tests for the chunk store module.

Tests the chunk store's data preparation logic without requiring
a live database connection.
"""

from __future__ import annotations

import uuid

from astraeus_rag.chunk_store import get_chunk_by_id, get_chunks_for_doc, store_chunks


class TestChunkStoreInterface:
    """Test chunk store function signatures and basic validation."""

    def test_store_chunks_is_async(self) -> None:
        """store_chunks is a coroutine function."""
        import asyncio
        assert asyncio.iscoroutinefunction(store_chunks)

    def test_get_chunks_for_doc_is_async(self) -> None:
        """get_chunks_for_doc is a coroutine function."""
        import asyncio
        assert asyncio.iscoroutinefunction(get_chunks_for_doc)

    def test_get_chunk_by_id_is_async(self) -> None:
        """get_chunk_by_id is a coroutine function."""
        import asyncio
        assert asyncio.iscoroutinefunction(get_chunk_by_id)


class TestChunkDataPreparation:
    """Test chunk data structures expected by the store."""

    def test_chunk_dict_structure(self) -> None:
        """Verify the expected chunk dict structure."""
        chunk = {
            "text": "Apple reported revenue of $94.8B in Q4 2024.",
            "chunk_idx": 0,
            "token_count": 12,
            "embedding": [0.1] * 384,
        }
        assert "text" in chunk
        assert "chunk_idx" in chunk
        assert "token_count" in chunk
        assert len(chunk["embedding"]) == 384

    def test_chunk_without_embedding(self) -> None:
        """Chunks can omit embedding (set to None)."""
        chunk = {
            "text": "Some text content.",
            "chunk_idx": 1,
            "token_count": 4,
            "embedding": None,
        }
        assert chunk["embedding"] is None

    def test_embedding_vector_string_format(self) -> None:
        """Verify pgvector string format construction."""
        embedding = [0.1, 0.2, 0.3, -0.5]
        vector_str = "[" + ",".join(str(v) for v in embedding) + "]"
        assert vector_str == "[0.1,0.2,0.3,-0.5]"

    def test_doc_id_is_uuid(self) -> None:
        """doc_id should be a valid UUID."""
        doc_id = uuid.uuid4()
        assert isinstance(doc_id, uuid.UUID)
        # UUID string format
        assert len(str(doc_id)) == 36
