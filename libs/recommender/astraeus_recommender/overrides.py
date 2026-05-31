"""Override-learning dataset management.

Captures every human override decision with rationale for future model training.
This module handles the dataset shape and export — no model training yet.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger("astraeus.recommender.overrides")


class OverrideRecord(BaseModel):
    """A single override event for the learning dataset."""

    rec_id: UUID
    run_id: UUID
    run_date: str  # ISO date
    ticker: str
    original_side: str
    original_weight: float
    override_weight: float | None
    decision: str  # approve | reject | override
    rationale: str
    regime_label: str
    composite_score: float
    component_attribution: dict[str, float]
    decided_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class OverrideDataset:
    """In-memory override dataset with export capability.

    In production this would be backed by the recommendation_decision table.
    The export produces a clean CSV suitable for future model training.
    """

    def __init__(self) -> None:
        self._records: list[OverrideRecord] = []

    def add(self, record: OverrideRecord) -> None:
        """Add an override record to the dataset."""
        self._records.append(record)
        logger.info(
            "override_recorded",
            rec_id=str(record.rec_id),
            ticker=record.ticker,
            decision=record.decision,
        )

    @property
    def count(self) -> int:
        return len(self._records)

    def export_csv(self) -> str:
        """Export the dataset as a CSV string."""
        if not self._records:
            return ""

        output = io.StringIO()
        fieldnames = [
            "rec_id",
            "run_id",
            "run_date",
            "ticker",
            "original_side",
            "original_weight",
            "override_weight",
            "decision",
            "rationale",
            "regime_label",
            "composite_score",
            "decided_at",
        ]
        # Add signal attribution columns
        all_signals: set[str] = set()
        for r in self._records:
            all_signals.update(r.component_attribution.keys())
        signal_cols = sorted(all_signals)
        fieldnames.extend([f"signal_{s}" for s in signal_cols])

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for r in self._records:
            row: dict[str, Any] = {
                "rec_id": str(r.rec_id),
                "run_id": str(r.run_id),
                "run_date": r.run_date,
                "ticker": r.ticker,
                "original_side": r.original_side,
                "original_weight": r.original_weight,
                "override_weight": r.override_weight,
                "decision": r.decision,
                "rationale": r.rationale,
                "regime_label": r.regime_label,
                "composite_score": r.composite_score,
                "decided_at": r.decided_at.isoformat(),
            }
            for s in signal_cols:
                row[f"signal_{s}"] = r.component_attribution.get(s, 0.0)
            writer.writerow(row)

        return output.getvalue()
