"""Stage 1: Aggregator — pulls daily features and creates an immutable input snapshot.

This stage is the single entry point for all data consumed by downstream stages.
It enforces PIT-correctness and produces a content-addressable hash for replay determinism.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import structlog

from ..contracts import DailyInputSnapshot

logger = structlog.get_logger("astraeus.recommender.stages.aggregate")


class AggregateStage:
    """Stage 1: Feature aggregation and snapshot creation.

    Pulls the latest PIT-correct features for the trading universe
    and persists an immutable snapshot keyed by content hash.
    """

    def __init__(
        self,
        feature_retriever: Any,  # astraeus_features.retrieval module or compatible
        universe_symbols: list[str],
        feature_names: list[str],
    ) -> None:
        self._retriever = feature_retriever
        self._symbols = universe_symbols
        self._feature_names = feature_names

    async def run(
        self,
        run_id: UUID,
        run_date: date,
        as_of_ts: datetime | None = None,
    ) -> DailyInputSnapshot:
        """Execute Stage 1: pull features and build snapshot.

        Args:
            run_id: Pipeline run identifier.
            run_date: The trading date for this run.
            as_of_ts: Point-in-time for feature retrieval. Defaults to run_date 06:30 ET.

        Returns:
            DailyInputSnapshot with content-addressable hash.
        """
        start = time.perf_counter()

        if as_of_ts is None:
            as_of_ts = datetime(
                run_date.year, run_date.month, run_date.day, 10, 30, tzinfo=UTC
            )

        logger.info(
            "stage1_aggregate_start",
            run_id=str(run_id),
            run_date=run_date.isoformat(),
            symbols_count=len(self._symbols),
            features_count=len(self._feature_names),
        )

        # Pull features via the PIT-correct retrieval client
        feature_matrix = await self._retriever.get(
            symbols=self._symbols,
            feature_names=self._feature_names,
            as_of_ts=as_of_ts,
        )

        # Compute content-addressable hash for replay determinism
        snapshot_hash = self._compute_hash(feature_matrix)

        elapsed_ms = (time.perf_counter() - start) * 1000

        snapshot = DailyInputSnapshot(
            run_id=run_id,
            run_date=run_date,
            snapshot_hash=snapshot_hash,
            symbols=self._symbols,
            feature_names=self._feature_names,
            feature_matrix=feature_matrix,
        )

        logger.info(
            "stage1_aggregate_complete",
            run_id=str(run_id),
            snapshot_hash=snapshot_hash[:16],
            elapsed_ms=round(elapsed_ms, 1),
            non_null_values=self._count_non_null(feature_matrix),
        )

        return snapshot

    @staticmethod
    def _compute_hash(matrix: dict[str, dict[str, float | None]]) -> str:
        """Deterministic SHA-256 of the feature matrix."""
        # Sort keys for determinism
        serialized = json.dumps(matrix, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()

    @staticmethod
    def _count_non_null(matrix: dict[str, dict[str, float | None]]) -> int:
        """Count non-null feature values for logging."""
        count = 0
        for features in matrix.values():
            for v in features.values():
                if v is not None:
                    count += 1
        return count
