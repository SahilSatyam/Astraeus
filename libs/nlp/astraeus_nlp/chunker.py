"""Token-aware text chunker — splits documents into overlapping chunks.

Recursive splitting strategy:
1. Split on paragraph boundaries (\n\n)
2. If a paragraph exceeds max_tokens, split on sentence boundaries
3. If a sentence exceeds max_tokens, split on token boundaries

Overlap ensures context continuity across chunk boundaries.
Token counting uses tiktoken (cl100k_base) for accuracy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger("astraeus.nlp.chunker")

# Sentence boundary regex (handles abbreviations reasonably)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

# Default chunk parameters
DEFAULT_MAX_TOKENS = 256
DEFAULT_OVERLAP_TOKENS = 32


@dataclass(frozen=True, slots=True)
class TextChunk:
    """A single text chunk with metadata."""

    text: str
    chunk_idx: int
    token_count: int
    char_start: int
    char_end: int


class TokenCounter:
    """Token counter using tiktoken for accurate token counts.

    Falls back to word-based approximation if tiktoken is unavailable.
    """

    def __init__(self, model: str = "cl100k_base") -> None:
        self._encoder = None
        try:
            import tiktoken

            self._encoder = tiktoken.get_encoding(model)
        except (ImportError, Exception):
            logger.warning("tiktoken_unavailable", msg="Falling back to word-based counting")

    def count(self, text: str) -> int:
        """Count tokens in text."""
        if self._encoder is not None:
            return len(self._encoder.encode(text))
        # Fallback: ~4 chars per token (rough approximation)
        return max(1, len(text) // 4)

    def truncate(self, text: str, max_tokens: int) -> str:
        """Truncate text to max_tokens."""
        if self._encoder is not None:
            tokens = self._encoder.encode(text)
            if len(tokens) <= max_tokens:
                return text
            return self._encoder.decode(tokens[:max_tokens])
        # Fallback: character-based truncation
        max_chars = max_tokens * 4
        return text[:max_chars]


class RecursiveChunker:
    """Recursive text chunker with token-aware splitting.

    Splits text into chunks of approximately max_tokens, with overlap_tokens
    of overlap between consecutive chunks for context continuity.
    """

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        counter: TokenCounter | None = None,
    ) -> None:
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens
        self._counter = counter or TokenCounter()

    def chunk(self, text: str) -> list[TextChunk]:
        """Split text into token-aware chunks.

        Returns ordered list of TextChunks with no gaps in coverage.
        """
        if not text.strip():
            return []

        # First pass: split on paragraphs
        paragraphs = text.split("\n\n")
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        # Merge small paragraphs, split large ones
        segments = self._normalize_segments(paragraphs)

        # Build chunks with overlap
        chunks = self._build_chunks_with_overlap(segments, text)

        return chunks

    def _normalize_segments(self, paragraphs: list[str]) -> list[str]:
        """Normalize paragraphs into segments that fit within max_tokens.

        Merges small paragraphs and splits large ones.
        """
        segments: list[str] = []

        for para in paragraphs:
            token_count = self._counter.count(para)

            if token_count <= self._max_tokens:
                segments.append(para)
            else:
                # Split on sentences
                sentences = _SENTENCE_RE.split(para)
                current = ""
                for sentence in sentences:
                    candidate = f"{current} {sentence}".strip() if current else sentence
                    if self._counter.count(candidate) <= self._max_tokens:
                        current = candidate
                    else:
                        if current:
                            segments.append(current)
                        # If single sentence exceeds max, truncate it
                        if self._counter.count(sentence) > self._max_tokens:
                            segments.append(self._counter.truncate(sentence, self._max_tokens))
                        else:
                            current = sentence
                if current:
                    segments.append(current)

        return segments

    def _build_chunks_with_overlap(
        self, segments: list[str], original_text: str
    ) -> list[TextChunk]:
        """Build final chunks by merging segments up to max_tokens with overlap."""
        if not segments:
            return []

        chunks: list[TextChunk] = []
        current_segments: list[str] = []
        current_tokens = 0

        for segment in segments:
            seg_tokens = self._counter.count(segment)

            if current_tokens + seg_tokens <= self._max_tokens:
                current_segments.append(segment)
                current_tokens += seg_tokens
            else:
                # Emit current chunk
                if current_segments:
                    chunk_text = "\n\n".join(current_segments)
                    char_start = original_text.find(current_segments[0])
                    char_start = max(0, char_start)
                    chunks.append(
                        TextChunk(
                            text=chunk_text,
                            chunk_idx=len(chunks),
                            token_count=current_tokens,
                            char_start=char_start,
                            char_end=char_start + len(chunk_text),
                        )
                    )

                # Start new chunk with overlap from previous
                overlap_segments = self._get_overlap_segments(current_segments)
                current_segments = overlap_segments + [segment]
                current_tokens = sum(self._counter.count(s) for s in current_segments)

        # Emit final chunk
        if current_segments:
            chunk_text = "\n\n".join(current_segments)
            char_start = original_text.find(current_segments[0])
            char_start = max(0, char_start)
            chunks.append(
                TextChunk(
                    text=chunk_text,
                    chunk_idx=len(chunks),
                    token_count=current_tokens,
                    char_start=char_start,
                    char_end=char_start + len(chunk_text),
                )
            )

        return chunks

    def _get_overlap_segments(self, segments: list[str]) -> list[str]:
        """Get trailing segments that fit within overlap_tokens."""
        overlap: list[str] = []
        tokens = 0
        for seg in reversed(segments):
            seg_tokens = self._counter.count(seg)
            if tokens + seg_tokens > self._overlap_tokens:
                break
            overlap.insert(0, seg)
            tokens += seg_tokens
        return overlap
