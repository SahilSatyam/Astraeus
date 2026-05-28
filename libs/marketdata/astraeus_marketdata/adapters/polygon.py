"""Polygon.io Market Data adapter.

Premium source for historical bars, trades, and quotes. Supports daily,
hourly, and minute bars with full market coverage.

Requires POLYGON_API_KEY environment variable.
Free tier: 5 API calls/minute. Starter: unlimited with 5 results/request.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import structlog

from astraeus_marketdata.adapters.base import AdapterResult, BarRecord, BaseAdapter
from astraeus_marketdata.ratelimit import RateLimiter
from astraeus_marketdata.retry import retry_with_backoff

logger = structlog.get_logger("astraeus.marketdata.polygon")

# Polygon free tier: 5 requests/minute; Starter: effectively unlimited
# We default to a conservative limit that works for free tier
_RATE_LIMIT = RateLimiter(rate=5, period=60.0)

_BASE_URL = "https://api.polygon.io"


class PolygonAdapter(BaseAdapter):
    """Fetch historical bars from Polygon.io Aggregates API."""

    source_name = "polygon"

    def __init__(self, api_key: str, rate_limit: int = 5) -> None:
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=30.0,
            params={"apiKey": api_key},
        )
        # Allow overriding rate limit for paid tiers
        self._rate_limiter = RateLimiter(rate=rate_limit, period=60.0)

    async def fetch_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        resolution: str = "1d",
    ) -> list[AdapterResult]:
        """Fetch bars for each symbol individually (Polygon aggregates are per-ticker)."""
        results: list[AdapterResult] = []
        for symbol in symbols:
            result = await self._fetch_symbol(symbol, start, end, resolution)
            results.append(result)
        return results

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        retryable_exceptions=(httpx.HTTPStatusError, httpx.TransportError),
    )
    async def _fetch_symbol(
        self,
        symbol: str,
        start: date,
        end: date,
        resolution: str,
    ) -> AdapterResult:
        """Fetch aggregates for a single symbol with pagination."""
        multiplier, timespan = self._parse_resolution(resolution)

        all_bars: list[BarRecord] = []
        raw_responses: list[bytes] = []
        next_url: str | None = None

        # Initial URL
        url = (
            f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}"
            f"/{start.isoformat()}/{end.isoformat()}"
        )

        while True:
            await self._rate_limiter.acquire()

            logger.debug(
                "polygon_fetch",
                symbol=symbol,
                start=str(start),
                end=str(end),
                next_url=next_url,
            )

            if next_url:
                # Polygon next_url is absolute; extract path
                resp = await self._client.get(
                    next_url,
                    params={"adjusted": "false", "sort": "asc", "limit": "50000"},
                )
            else:
                resp = await self._client.get(
                    url,
                    params={"adjusted": "false", "sort": "asc", "limit": "50000"},
                )

            resp.raise_for_status()

            raw_bytes = resp.content
            raw_responses.append(raw_bytes)
            data = resp.json()

            results_list = data.get("results", [])
            for bar in results_list:
                # Polygon timestamps are Unix ms
                ts = datetime.fromtimestamp(bar["t"] / 1000, tz=UTC)
                all_bars.append(
                    BarRecord(
                        symbol=symbol,
                        ts=ts,
                        resolution=resolution,
                        open=Decimal(str(bar["o"])),
                        high=Decimal(str(bar["h"])),
                        low=Decimal(str(bar["l"])),
                        close=Decimal(str(bar["c"])),
                        volume=bar.get("v"),
                        vwap=Decimal(str(bar["vw"])) if bar.get("vw") else None,
                        trades=bar.get("n"),
                    )
                )

            # Check for pagination
            next_url = data.get("next_url")
            if not next_url:
                break

        logger.info(
            "polygon_fetch_complete",
            symbol=symbol,
            bars=len(all_bars),
            pages=len(raw_responses),
        )

        combined_raw = b"\n".join(raw_responses)

        return AdapterResult(
            bars=all_bars,
            raw_response=combined_raw,
            source=self.source_name,
            endpoint=f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}",
            symbols_requested=[symbol],
            request_time=datetime.now(tz=UTC),
        )

    @staticmethod
    def _parse_resolution(resolution: str) -> tuple[int, str]:
        """Convert internal resolution format to Polygon multiplier/timespan."""
        mapping: dict[str, tuple[int, str]] = {
            "1m": (1, "minute"),
            "5m": (5, "minute"),
            "15m": (15, "minute"),
            "1h": (1, "hour"),
            "1d": (1, "day"),
            "1wk": (1, "week"),
        }
        return mapping.get(resolution, (1, "day"))

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
