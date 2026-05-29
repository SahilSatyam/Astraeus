"""BERTopic wrapper for topic modeling on financial text.

Re-fits every 30 days on a 90-day rolling window. Each refit produces a
new model_run_id — never overwrites. Topic drift is a first-class observable.

Topic alignment across refits uses embedding centroid matching.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import structlog

logger = structlog.get_logger("astraeus.nlp.topic")


@dataclass(frozen=True, slots=True)
class TopicAssignment:
    """Topic assignment for a single chunk."""

    chunk_id: uuid.UUID
    topic_id: int
    probability: float
    topic_words: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TopicModelResult:
    """Result of a BERTopic fit/transform run."""

    model_run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    fit_window_from: date = field(default_factory=date.today)
    fit_window_to: date = field(default_factory=date.today)
    n_topics: int = 0
    topic_summary: dict[int, list[str]] = field(default_factory=dict)
    assignments: list[TopicAssignment] = field(default_factory=list)


class TopicModeler:
    """BERTopic-based topic modeling for financial documents.

    Fits on a rolling window of document chunks. Produces topic assignments
    and topic summaries (top words per topic).
    """

    def __init__(
        self,
        n_topics: int | str = "auto",
        min_topic_size: int = 10,
        embedding_model: str = "BAAI/bge-small-en-v1.5",
    ) -> None:
        self._n_topics = n_topics
        self._min_topic_size = min_topic_size
        self._embedding_model = embedding_model
        self._model = None

    def fit_transform(
        self,
        texts: list[str],
        chunk_ids: list[uuid.UUID],
        embeddings: np.ndarray | None = None,
        window_from: date | None = None,
        window_to: date | None = None,
    ) -> TopicModelResult:
        """Fit BERTopic on texts and return topic assignments.

        Args:
            texts: Document chunk texts to cluster.
            chunk_ids: Corresponding chunk UUIDs.
            embeddings: Pre-computed embeddings (optional; BERTopic computes if None).
            window_from: Start of the fit window.
            window_to: End of the fit window.

        Returns:
            TopicModelResult with assignments and topic summaries.
        """
        from bertopic import BERTopic

        logger.info(
            "topic_model_fitting",
            n_docs=len(texts),
            window_from=str(window_from),
            window_to=str(window_to),
        )

        # Configure BERTopic
        nr_topics = None if self._n_topics == "auto" else int(self._n_topics)
        model = BERTopic(
            nr_topics=nr_topics,
            min_topic_size=self._min_topic_size,
            embedding_model=self._embedding_model,
            verbose=False,
        )

        # Fit and transform
        topics, probs = model.fit_transform(texts, embeddings=embeddings)

        # Build topic summary
        topic_info = model.get_topic_info()
        topic_summary: dict[int, list[str]] = {}
        for _, row in topic_info.iterrows():
            topic_id = row["Topic"]
            if topic_id == -1:
                continue  # Skip outlier topic
            topic_words = model.get_topic(topic_id)
            if topic_words:
                topic_summary[topic_id] = [word for word, _ in topic_words[:10]]

        # Build assignments
        assignments: list[TopicAssignment] = []
        for i, (topic_id, chunk_id) in enumerate(zip(topics, chunk_ids, strict=False)):
            prob = float(probs[i]) if probs is not None and i < len(probs) else 0.0
            if topic_id == -1:
                continue  # Skip outlier assignments
            assignments.append(
                TopicAssignment(
                    chunk_id=chunk_id,
                    topic_id=int(topic_id),
                    probability=prob,
                    topic_words=topic_summary.get(int(topic_id), []),
                )
            )

        result = TopicModelResult(
            fit_window_from=window_from or date.today(),
            fit_window_to=window_to or date.today(),
            n_topics=len(topic_summary),
            topic_summary=topic_summary,
            assignments=assignments,
        )

        self._model = model

        logger.info(
            "topic_model_fitted",
            n_topics=result.n_topics,
            n_assignments=len(assignments),
            model_run_id=str(result.model_run_id),
        )

        return result

    def compute_drift(
        self, previous_summary: dict[int, list[str]], current_summary: dict[int, list[str]]
    ) -> float:
        """Compute topic drift between two model runs.

        Uses vocabulary overlap as a proxy for topic stability.
        Returns a score in [0, 1] where 0 = identical, 1 = completely different.
        """
        if not previous_summary or not current_summary:
            return 1.0

        overlaps: list[float] = []
        for _topic_id, prev_words in previous_summary.items():
            # Find best-matching topic in current run
            best_overlap = 0.0
            prev_set = set(prev_words)
            for curr_words in current_summary.values():
                curr_set = set(curr_words)
                if prev_set or curr_set:
                    overlap = len(prev_set & curr_set) / max(len(prev_set | curr_set), 1)
                    best_overlap = max(best_overlap, overlap)
            overlaps.append(best_overlap)

        avg_overlap = sum(overlaps) / max(len(overlaps), 1)
        return 1.0 - avg_overlap
