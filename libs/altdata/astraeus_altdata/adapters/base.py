"""Base adapter interface for all alt-data source adapters.

Every source (Reddit, RSS, EDGAR, etc.) implements this protocol.
The ingestion worker calls adapters through this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from astraeus_altdata.documents import AdapterFetchResult, DocumentSource


class BaseDocumentAdapter(ABC):
    """Abstract base for all alt-data source adapters."""

    source: DocumentSource

    @abstractmethod
    async def fetch(self, cursor: str | None = None) -> AdapterFetchResult:
        """Fetch a batch of documents from the source.

        Args:
            cursor: Pagination cursor from a previous fetch. None for first fetch.

        Returns:
            AdapterFetchResult with documents and next_cursor for pagination.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any held resources."""
        ...

    async def fetch_all(self, max_pages: int = 100) -> AsyncIterator[AdapterFetchResult]:
        """Paginate through all available documents.

        Yields one AdapterFetchResult per page until exhausted or max_pages reached.
        """
        cursor: str | None = None
        for _ in range(max_pages):
            result = await self.fetch(cursor=cursor)
            yield result
            if result.next_cursor is None or result.is_empty:
                break
            cursor = result.next_cursor
