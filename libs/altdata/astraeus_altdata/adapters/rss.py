"""RSS news adapter — ingests articles from financial news feeds.

Fetches from a curated list of RSS/Atom feeds. Only ingests sources
where we can prove rights (public RSS feeds with no scraping restrictions).

For body extraction: uses the RSS summary/content field. If the feed only
provides a snippet, we store that — no scraping of full articles unless
explicitly licensed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
import structlog

from astraeus_altdata.adapters.base import BaseDocumentAdapter
from astraeus_altdata.documents import AdapterFetchResult, DocumentSource, RawDocument

logger = structlog.get_logger("astraeus.altdata.adapters.rss")

# Default RSS feeds — public, finance-focused, no paywall scraping
DEFAULT_FEEDS: list[dict[str, str]] = [
    {"url": "https://feeds.reuters.com/reuters/businessNews", "name": "Reuters Business"},
    {"url": "https://feeds.reuters.com/reuters/companyNews", "name": "Reuters Company"},
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml", "name": "BBC Business"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "name": "NYT Business"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "name": "CNBC"},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories/", "name": "MarketWatch"},
    {"url": "https://seekingalpha.com/market_currents.xml", "name": "Seeking Alpha Currents"},
    {"url": "https://finance.yahoo.com/news/rssindex", "name": "Yahoo Finance"},
]


class RSSAdapter(BaseDocumentAdapter):
    """RSS/Atom feed adapter for financial news.

    Fetches and parses feeds using feedparser. Each entry becomes a RawDocument.
    Handles both RSS 2.0 and Atom formats transparently.
    """

    source = DocumentSource.RSS

    def __init__(
        self,
        feeds: list[dict[str, str]] | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._feeds = feeds or DEFAULT_FEEDS
        self._client = http_client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = http_client is None
        self._current_feed_idx = 0

    async def fetch(self, cursor: str | None = None) -> AdapterFetchResult:
        """Fetch entries from the next feed in the list.

        Cursor is the feed index for round-robin pagination.
        """
        import feedparser

        if cursor is not None:
            self._current_feed_idx = int(cursor)

        if self._current_feed_idx >= len(self._feeds):
            return AdapterFetchResult(source=self.source)

        feed_config = self._feeds[self._current_feed_idx]
        feed_url = feed_config["url"]
        feed_name = feed_config.get("name", feed_url)
        documents: list[RawDocument] = []
        errors: list[str] = []

        try:
            response = await self._client.get(feed_url)
            response.raise_for_status()

            parsed = feedparser.parse(response.text)

            for entry in parsed.entries:
                try:
                    doc = self._entry_to_document(entry, feed_name)
                    documents.append(doc)
                except Exception as e:
                    errors.append(f"Entry: {e}")

        except httpx.HTTPStatusError as e:
            errors.append(f"HTTP {e.response.status_code} from {feed_name}")
            logger.warning("rss_http_error", feed=feed_name, status=e.response.status_code)
        except Exception as e:
            errors.append(f"Feed {feed_name}: {e}")
            logger.exception("rss_fetch_error", feed=feed_name)

        next_idx = self._current_feed_idx + 1
        next_cursor = str(next_idx) if next_idx < len(self._feeds) else None

        logger.info(
            "rss_fetch_complete",
            feed=feed_name,
            documents=len(documents),
            errors=len(errors),
        )

        return AdapterFetchResult(
            documents=documents,
            source=self.source,
            fetch_completed_at=datetime.now(tz=UTC),
            next_cursor=next_cursor,
            errors=errors,
        )

    def _entry_to_document(self, entry: Any, feed_name: str) -> RawDocument:
        """Convert a feedparser entry to a RawDocument."""
        # Extract body from content or summary
        body = ""
        if hasattr(entry, "content") and entry.content:
            body = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            body = entry.summary or ""

        # Parse publish timestamp
        publish_ts = datetime.now(tz=UTC)
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                import time

                publish_ts = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=UTC)
            except (TypeError, ValueError, OverflowError):
                pass
        elif hasattr(entry, "published") and entry.published:
            try:
                publish_ts = parsedate_to_datetime(entry.published).astimezone(UTC)
            except (TypeError, ValueError):
                pass

        # Generate stable source_doc_id
        link = getattr(entry, "link", "") or ""
        entry_id = getattr(entry, "id", "") or link
        source_doc_id = f"rss_{feed_name}_{entry_id}"

        return RawDocument(
            source=DocumentSource.RSS,
            source_doc_id=source_doc_id,
            title=getattr(entry, "title", None),
            body=body,
            url=link or None,
            publish_ts=publish_ts,
            metadata={
                "feed_name": feed_name,
                "author": getattr(entry, "author", None),
                "tags": [t.get("term", "") for t in getattr(entry, "tags", [])],
            },
        )

    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._owns_client:
            await self._client.aclose()
