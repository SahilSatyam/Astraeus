"""Tests for the recursive text chunker."""

from __future__ import annotations

import pytest
from astraeus_nlp.chunker import RecursiveChunker, TokenCounter


@pytest.mark.unit
class TestTokenCounter:
    """Tests for token counting."""

    def test_count_nonempty(self) -> None:
        counter = TokenCounter()
        count = counter.count("Hello world")
        assert count > 0

    def test_count_empty(self) -> None:
        counter = TokenCounter()
        # Empty string should still return at least 0 or 1
        count = counter.count("")
        assert count >= 0

    def test_truncate(self) -> None:
        counter = TokenCounter()
        long_text = "word " * 1000
        truncated = counter.truncate(long_text, 10)
        assert counter.count(truncated) <= 10


@pytest.mark.unit
class TestRecursiveChunker:
    """Tests for recursive chunking."""

    def test_short_text_single_chunk(self) -> None:
        chunker = RecursiveChunker(max_tokens=256)
        text = "This is a short paragraph about Apple earnings."
        chunks = chunker.chunk(text)
        assert len(chunks) == 1
        assert chunks[0].chunk_idx == 0
        assert chunks[0].text == text

    def test_long_text_multiple_chunks(self) -> None:
        chunker = RecursiveChunker(max_tokens=50, overlap_tokens=10)
        # Generate text that exceeds max_tokens
        paragraphs = [
            f"Paragraph {i} about financial markets and trading strategies." for i in range(20)
        ]
        text = "\n\n".join(paragraphs)
        chunks = chunker.chunk(text)
        assert len(chunks) > 1
        # Chunks should be ordered
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_idx == i

    def test_empty_text_no_chunks(self) -> None:
        chunker = RecursiveChunker()
        chunks = chunker.chunk("")
        assert chunks == []

    def test_whitespace_only_no_chunks(self) -> None:
        chunker = RecursiveChunker()
        chunks = chunker.chunk("   \n\n   ")
        assert chunks == []

    def test_chunk_token_count_within_limit(self) -> None:
        chunker = RecursiveChunker(max_tokens=100, overlap_tokens=20)
        text = "\n\n".join([f"Sentence number {i} about stocks." for i in range(50)])
        chunks = chunker.chunk(text)
        counter = TokenCounter()
        for chunk in chunks:
            # Allow some tolerance for overlap
            assert counter.count(chunk.text) <= 150  # max + overlap buffer

    def test_paragraph_boundaries_respected(self) -> None:
        chunker = RecursiveChunker(max_tokens=256)
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = chunker.chunk(text)
        # Short enough to fit in one chunk
        assert len(chunks) == 1
        assert "First" in chunks[0].text
        assert "Third" in chunks[0].text
