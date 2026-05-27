"""Base adapter interface for all market data sources.

Every source adapter (Alpaca, Yahoo, FRED, etc.) implements this protocol.
The ingestion worker calls adapters through this interface, ensuring uniform
error handling, rate limiting, and lineage tracking regardless of source.
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class BarRecord:
    """A single OHLCV bar from any source."""

    symbol: str
    ts: datetime
    resolution: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None = None
    vwap: Decimal | None = None
    trades: int | None = None


@dataclass(slots=True)
class AdapterResult:
    """Result of a single adapter fetch call.

    Contains the parsed bars, the raw response bytes (for MinIO archival),
    and metadata for lineage tracking.
    """

    bars: list[BarRecord] = field(default_factory=list)
    raw_response: bytes = b""
    source: str = ""
    endpoint: str = ""
    symbols_requested: list[str] = field(default_factory=list)
    request_time: datetime | None = None
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def response_hash(self) -> bytes:
        """SHA-256 of the raw response for deduplication and lineage."""
        return hashlib.sha256(self.raw_response).digest()

    @property
    def is_empty(self) -> bool:
        return len(self.bars) == 0


def compute_payload_hash(bar: BarRecord, source: str) -> bytes:
    """Deterministic hash for a single bar record.

    Used as the idempotency key: same source + same data = same hash.
    """
    canonical = (
        f"{source}|{bar.symbol}|{bar.ts.isoformat()}|{bar.resolution}|"
        f"{bar.open}|{bar.high}|{bar.low}|{bar.close}|"
        f"{bar.volume}|{bar.vwap}|{bar.trades}"
    )
    return hashlib.sha256(canonical.encode()).digest()


class BaseAdapter(ABC):
    """Abstract base for all market data source adapters.

    Subclasses implement fetch_bars for historical data retrieval.
    The adapter is responsible for:
    - Pagination (if the source paginates)
    - Rate limiting (via the shared RateLimiter)
    - Returning raw response bytes alongside parsed data
    """

    source_name: str = "unknown"

    @abstractmethod
    async def fetch_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        resolution: str = "1d",
    ) -> list[AdapterResult]:
        """Fetch historical OHLCV bars for the given symbols and date range.

        Returns one AdapterResult per API call made (may be multiple for
        paginated sources or per-symbol APIs).
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any held resources (HTTP clients, connections)."""
        ...
