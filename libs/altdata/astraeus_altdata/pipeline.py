"""NLP pipeline orchestrator — processes documents through the full NLP stack.

Pipeline stages:
1. Clean: HTML strip, normalize, remove boilerplate
2. Chunk: Token-aware recursive splitting
3. NER + Entity Link: Extract and resolve entities to tickers
4. Sentiment: FinBERT scoring per document per ticker
5. Embed: Sentence-transformer embeddings per chunk
6. Store: Persist chunks, entities, sentiment, embeddings

Each stage is independently observable and can be retried.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from astraeus_nlp.chunker import RecursiveChunker, TextChunk
from astraeus_nlp.cleaner import clean_document
from astraeus_nlp.embeddings import SentenceEmbedder
from astraeus_nlp.entity_linker import EntityLinker, LinkedEntity
from astraeus_nlp.ner import FinanceNER
from astraeus_nlp.sentiment import FinBERTSentiment

from astraeus_altdata.documents import RawDocument

if TYPE_CHECKING:
    from astraeus_entities.ticker_dict import TickerDictionary

logger = structlog.get_logger("astraeus.altdata.pipeline")


@dataclass(slots=True)
class PipelineResult:
    """Result of processing a single document through the NLP pipeline."""

    doc_id: uuid.UUID
    n_chunks: int = 0
    n_entities: int = 0
    tickers_found: list[str] = field(default_factory=list)
    sentiment_scores: dict[str, float] = field(default_factory=dict)
    processing_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


class NLPPipeline:
    """Orchestrates the full NLP processing pipeline for documents.

    Lazy-loads models on first use. Designed for batch processing
    but supports single-document mode for streaming.
    """

    def __init__(
        self,
        ticker_dictionary: TickerDictionary,
        *,
        ner: FinanceNER | None = None,
        sentiment: FinBERTSentiment | None = None,
        embedder: SentenceEmbedder | None = None,
        chunker: RecursiveChunker | None = None,
        entity_linker: EntityLinker | None = None,
        confidence_threshold: float = 0.7,
    ) -> None:
        self._ner = ner or FinanceNER()
        self._sentiment = sentiment or FinBERTSentiment()
        self._embedder = embedder or SentenceEmbedder()
        self._chunker = chunker or RecursiveChunker()
        self._linker = entity_linker or EntityLinker(
            dictionary=ticker_dictionary,
            confidence_threshold=confidence_threshold,
        )

    def process_document(self, doc: RawDocument) -> PipelineResult:
        """Process a single document through the full NLP pipeline.

        Returns a PipelineResult with all extracted data ready for persistence.
        """
        start = time.perf_counter()
        result = PipelineResult(doc_id=doc.doc_id)

        try:
            # 1. Clean
            cleaned_text = clean_document(doc.body)
            if not cleaned_text.strip():
                result.errors.append("Empty after cleaning")
                return result

            # 2. Chunk
            chunks = self._chunker.chunk(cleaned_text)
            result.n_chunks = len(chunks)

            if not chunks:
                result.errors.append("No chunks produced")
                return result

            # 3. NER + Entity Linking
            all_entities: list[LinkedEntity] = []
            for chunk in chunks:
                ner_spans = self._ner.extract(chunk.text)
                linked = self._linker.link(chunk.text, ner_spans)
                all_entities.extend(linked)

            result.n_entities = len(all_entities)
            result.tickers_found = list({e.canonical_id for e in all_entities})

            # 4. Sentiment (per document, aggregated across chunks)
            if result.tickers_found:
                # Score the full cleaned text for overall sentiment
                sentiment = self._sentiment.analyze(cleaned_text[:2048])
                for ticker in result.tickers_found:
                    result.sentiment_scores[ticker] = sentiment.score

            # 5. Embeddings are computed per chunk (stored separately)
            # The actual embedding computation happens at persistence time
            # to allow batching across documents

        except Exception as e:
            result.errors.append(str(e))
            logger.exception("pipeline_error", doc_id=str(doc.doc_id))

        result.processing_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "pipeline_processed",
            doc_id=str(doc.doc_id),
            chunks=result.n_chunks,
            entities=result.n_entities,
            tickers=result.tickers_found,
            ms=round(result.processing_ms, 1),
        )

        return result

    def embed_chunks(self, chunks: list[TextChunk]) -> list[list[float]]:
        """Compute embeddings for a batch of chunks.

        Separated from process_document to allow batching across documents.
        """
        texts = [chunk.text for chunk in chunks]
        results = self._embedder.embed_batch(texts)
        return [r.vector for r in results]
