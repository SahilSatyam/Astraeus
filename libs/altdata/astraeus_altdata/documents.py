"""Document model — the core data structure for all alt-data sources.

Every piece of text (Reddit post, news article, SEC filing, transcript)
enters the system as a RawDocument. The three-timestamp discipline is
enforced here: event_ts, publish_ts, ingest_ts.

`available_at = max(publish_ts, ingest_ts)` is computed at write time
and used for all PIT joins downstream.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class DocumentSource(StrEnum):
    """Canonical source identifiers."""

    REDDIT = "reddit"
    RSS = "rss"
    EDGAR = "edgar"
    TRANSCRIPT = "transcript"
    GDELT = "gdelt"


@dataclass(frozen=True, slots=True)
class RawDocument:
    """A single document from any alt-data source.

    This is the in-memory representation before persistence. The adapter
    produces these; the ingestion worker persists them.
    """

    source: DocumentSource
    source_doc_id: str  # vendor-side unique ID
    title: str | None = None
    body: str = ""  # full text content
    url: str | None = None
    language: str = "en"
    event_ts: datetime | None = None  # when the event happened
    publish_ts: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def doc_id(self) -> uuid.UUID:
        """Deterministic UUID from source + source_doc_id for idempotency."""
        canonical = f"{self.source}|{self.source_doc_id}"
        return uuid.uuid5(uuid.NAMESPACE_URL, canonical)

    @property
    def body_hash(self) -> bytes:
        """SHA-256 of the body for deduplication."""
        return hashlib.sha256(self.body.encode()).digest()

    @property
    def available_at(self) -> datetime:
        """PIT-correct availability timestamp.

        This is the earliest time we could have used this document in a
        backtest. It's max(publish_ts, ingest_ts) — but since ingest_ts
        is set at write time, we use publish_ts here and let the DB
        compute the final available_at.
        """
        return self.publish_ts


@dataclass(slots=True)
class AdapterFetchResult:
    """Result of a single adapter fetch cycle.

    Contains the documents fetched, pagination state, and metadata
    for observability.
    """

    documents: list[RawDocument] = field(default_factory=list)
    source: DocumentSource = DocumentSource.RSS
    fetch_started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    fetch_completed_at: datetime | None = None
    next_cursor: str | None = None  # for pagination
    errors: list[str] = field(default_factory=list)
    rate_limited: bool = False

    @property
    def count(self) -> int:
        return len(self.documents)

    @property
    def is_empty(self) -> bool:
        return len(self.documents) == 0
