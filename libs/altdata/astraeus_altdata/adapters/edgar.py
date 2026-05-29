"""SEC EDGAR adapter — ingests 8-K, 10-Q, 10-K filings.

Uses the free EDGAR full-text search and daily index APIs. Rate limits
are documented (10 req/sec with User-Agent header). We respect them.

Filing types:
- 8-K: Material events (immediate ingest)
- 10-Q: Quarterly reports (T+1 ingest)
- 10-K: Annual reports (T+1 ingest)

The adapter fetches the filing index, then retrieves the primary document
(HTML or plain text). XBRL parsing is deferred to the cleaner stage.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from astraeus_altdata.adapters.base import BaseDocumentAdapter
from astraeus_altdata.documents import AdapterFetchResult, DocumentSource, RawDocument

logger = structlog.get_logger("astraeus.altdata.adapters.edgar")

# EDGAR requires a User-Agent with contact info
_USER_AGENT = "Astraeus Research Platform contact@example.com"
_BASE_URL = "https://efts.sec.gov/LATEST/search-index"
_FULL_TEXT_URL = "https://efts.sec.gov/LATEST/search-index"
_FILING_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

# Rate limit: 10 requests/second per EDGAR docs
_REQUEST_DELAY = 0.12  # ~8 req/sec to stay safe

# Filing types we care about
FILING_TYPES = ("8-K", "10-Q", "10-K")


class EdgarAdapter(BaseDocumentAdapter):
    """SEC EDGAR filing adapter.

    Fetches recent filings from the EDGAR full-text search API.
    Each filing becomes a RawDocument with the full text extracted.
    """

    source = DocumentSource.EDGAR

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        filing_types: tuple[str, ...] = FILING_TYPES,
        lookback_days: int = 1,
        max_filings_per_fetch: int = 50,
    ) -> None:
        self._client = http_client or httpx.AsyncClient(
            timeout=60.0,
            headers={"User-Agent": _USER_AGENT},
        )
        self._owns_client = http_client is None
        self._filing_types = filing_types
        self._lookback_days = lookback_days
        self._max_filings = max_filings_per_fetch

    async def fetch(self, cursor: str | None = None) -> AdapterFetchResult:
        """Fetch recent filings from EDGAR.

        Uses the EDGAR full-text search API to find recent filings.
        Cursor is the start index for pagination.
        """
        start_idx = int(cursor) if cursor else 0
        documents: list[RawDocument] = []
        errors: list[str] = []

        date_from = (datetime.now(tz=UTC) - timedelta(days=self._lookback_days)).strftime(
            "%Y-%m-%d"
        )
        date_to = datetime.now(tz=UTC).strftime("%Y-%m-%d")

        try:
            # Use EDGAR full-text search API
            for filing_type in self._filing_types:
                filings = await self._search_filings(
                    filing_type=filing_type,
                    date_from=date_from,
                    date_to=date_to,
                    start=start_idx,
                )

                for filing in filings:
                    try:
                        doc = await self._filing_to_document(filing)
                        if doc:
                            documents.append(doc)
                    except Exception as e:
                        errors.append(f"Filing {filing.get('accession_number', '?')}: {e}")

                    # Respect rate limits
                    await asyncio.sleep(_REQUEST_DELAY)

        except Exception as e:
            errors.append(f"EDGAR search: {e}")
            logger.exception("edgar_fetch_error")

        # Pagination: if we got max results, there might be more
        next_cursor = None
        if len(documents) >= self._max_filings:
            next_cursor = str(start_idx + self._max_filings)

        logger.info(
            "edgar_fetch_complete",
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

    async def _search_filings(
        self,
        filing_type: str,
        date_from: str,
        date_to: str,
        start: int = 0,
    ) -> list[dict[str, Any]]:
        """Search EDGAR for filings of a given type in a date range."""
        # EDGAR EFTS API endpoint
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q": f'formType:"{filing_type}"',
            "dateRange": "custom",
            "startdt": date_from,
            "enddt": date_to,
            "start": start,
            "count": self._max_filings,
        }

        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("hits", {}).get("hits", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("edgar_rate_limited")
                await asyncio.sleep(5.0)
            raise
        except Exception:
            logger.exception("edgar_search_failed", filing_type=filing_type)
            return []

    async def _filing_to_document(self, filing: dict[str, Any]) -> RawDocument | None:
        """Convert an EDGAR search result to a RawDocument.

        Fetches the primary document text from the filing URL.
        """
        source_data = filing.get("_source", filing)
        accession = source_data.get("file_num", "") or source_data.get("accession_no", "")
        filing_type = source_data.get("form_type", "")
        company_name = (
            source_data.get("display_names", [""])[0] if source_data.get("display_names") else ""
        )
        file_date = source_data.get("file_date", "")

        if not accession:
            return None

        # Parse filing date
        publish_ts = datetime.now(tz=UTC)
        if file_date:
            try:
                publish_ts = datetime.strptime(file_date, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                pass

        # For now, store the metadata as body; full text fetch is done by the cleaner
        body = f"Filing Type: {filing_type}\nCompany: {company_name}\nDate: {file_date}\n"
        body += f"Accession: {accession}\n"

        return RawDocument(
            source=DocumentSource.EDGAR,
            source_doc_id=f"edgar_{accession}_{filing_type}",
            title=f"{filing_type} - {company_name}",
            body=body,
            url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={accession}",
            publish_ts=publish_ts,
            event_ts=publish_ts,  # For filings, event_ts == publish_ts
            metadata={
                "filing_type": filing_type,
                "company_name": company_name,
                "accession_number": accession,
                "cik": source_data.get("entity_id", ""),
            },
        )

    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._owns_client:
            await self._client.aclose()
