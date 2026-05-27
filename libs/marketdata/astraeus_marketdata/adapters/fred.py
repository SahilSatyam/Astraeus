"""FRED (Federal Reserve Economic Data) adapter.

Free, reliable source for macro economic series (GDP, CPI, unemployment,
treasury yields, etc.). Low-frequency data, minimal rate-limit concerns.

Requires FRED_API_KEY environment variable.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx
import structlog

from astraeus_marketdata.adapters.base import AdapterResult, BarRecord, BaseAdapter
from astraeus_marketdata.ratelimit import RateLimiter
from astraeus_marketdata.retry import retry_with_backoff

logger = structlog.get_logger("astraeus.marketdata.fred")

# FRED: 120 requests/minute
_RATE_LIMIT = RateLimiter(rate=120, period=60.0)

_BASE_URL = "https://api.stlouisfed.org/fred"


class FredAdapter(BaseAdapter):
    """Fetch macro economic series from FRED."""

    source_name = "fred"

    def __init__(self, api_key: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=30.0,
        )
        self._api_key = api_key

    async def fetch_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        resolution: str = "1d",
    ) -> list[AdapterResult]:
        """Fetch FRED series. Each 'symbol' is a FRED series ID (e.g., GDP, CPIAUCSL)."""
        results: list[AdapterResult] = []
        for series_id in symbols:
            result = await self._fetch_series(series_id, start, end)
            results.append(result)
        return results

    @retry_with_backoff(
        max_attempts=3,
        base_delay=1.0,
        retryable_exceptions=(httpx.HTTPStatusError, httpx.TransportError),
    )
    async def _fetch_series(
        self,
        series_id: str,
        start: date,
        end: date,
    ) -> AdapterResult:
        """Fetch a single FRED series."""
        await _RATE_LIMIT.acquire()

        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
            "sort_order": "asc",
        }

        logger.debug("fred_fetch_start", series_id=series_id)

        resp = await self._client.get("/series/observations", params=params)
        resp.raise_for_status()

        raw_bytes = resp.content
        data = resp.json()

        bars: list[BarRecord] = []
        for obs in data.get("observations", []):
            value_str = obs.get("value", ".")
            if value_str == ".":
                continue  # FRED uses "." for missing values

            try:
                value = Decimal(value_str)
            except InvalidOperation:
                continue

            obs_date = date.fromisoformat(obs["date"])
            ts = datetime(obs_date.year, obs_date.month, obs_date.day, tzinfo=timezone.utc)

            # FRED series are stored as bars with value in all OHLC fields
            # (they're point-in-time observations, not candles)
            bars.append(
                BarRecord(
                    symbol=series_id,
                    ts=ts,
                    resolution="1d",
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=None,
                    vwap=None,
                    trades=None,
                )
            )

        logger.info("fred_fetch_complete", series_id=series_id, observations=len(bars))

        return AdapterResult(
            bars=bars,
            raw_response=raw_bytes,
            source=self.source_name,
            endpoint=f"/fred/series/observations?series_id={series_id}",
            symbols_requested=[series_id],
            request_time=datetime.now(tz=timezone.utc),
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
