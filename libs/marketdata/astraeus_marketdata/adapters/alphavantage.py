"""Alpha Vantage Market Data adapter.

Free tier provides daily OHLCV with 25 requests/day (premium: 75-600/min).
Good for cross-validation against Yahoo/Polygon data.

Requires ALPHAVANTAGE_API_KEY environment variable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import structlog

from astraeus_marketdata.adapters.base import AdapterResult, BarRecord, BaseAdapter
from astraeus_marketdata.ratelimit import RateLimiter
from astraeus_marketdata.retry import retry_with_backoff

logger = structlog.get_logger("astraeus.marketdata.alphavantage")

# Free tier: 25 requests/day ≈ 1 request per ~3.5 minutes
# We set a conservative 5/min for premium users; free tier callers
# should instantiate with rate_limit=1, period=60
_RATE_LIMIT = RateLimiter(rate=5, period=60.0)

_BASE_URL = "https://www.alphavantage.co"


class AlphaVantageAdapter(BaseAdapter):
    """Fetch historical bars from Alpha Vantage."""

    source_name = "alphavantage"

    def __init__(self, api_key: str, rate_limit: int = 5) -> None:
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=30.0,
        )
        self._api_key = api_key
        self._rate_limiter = RateLimiter(rate=rate_limit, period=60.0)

    async def fetch_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        resolution: str = "1d",
    ) -> list[AdapterResult]:
        """Fetch bars for each symbol individually."""
        results: list[AdapterResult] = []
        for symbol in symbols:
            result = await self._fetch_symbol(symbol, start, end, resolution)
            results.append(result)
        return results

    @retry_with_backoff(
        max_attempts=3,
        base_delay=5.0,
        retryable_exceptions=(httpx.HTTPStatusError, httpx.TransportError),
    )
    async def _fetch_symbol(
        self,
        symbol: str,
        start: date,
        end: date,
        resolution: str,
    ) -> AdapterResult:
        """Fetch time series for a single symbol."""
        await self._rate_limiter.acquire()

        function, interval = self._resolve_function(resolution)

        params: dict[str, str] = {
            "function": function,
            "symbol": symbol,
            "apikey": self._api_key,
            "datatype": "json",
            "outputsize": "full",
        }
        if interval:
            params["interval"] = interval

        logger.debug("alphavantage_fetch_start", symbol=symbol, function=function)

        resp = await self._client.get("/query", params=params)
        resp.raise_for_status()

        raw_bytes = resp.content
        data = resp.json()

        # Alpha Vantage returns errors in the response body
        if "Error Message" in data:
            logger.error(
                "alphavantage_error",
                symbol=symbol,
                error=data["Error Message"],
            )
            return AdapterResult(
                bars=[],
                raw_response=raw_bytes,
                source=self.source_name,
                endpoint=f"/query?function={function}&symbol={symbol}",
                symbols_requested=[symbol],
                request_time=datetime.now(tz=UTC),
            )

        if "Note" in data:
            # Rate limit hit
            logger.warning("alphavantage_rate_limit", symbol=symbol, note=data["Note"])
            raise httpx.HTTPStatusError(
                "Rate limit exceeded",
                request=resp.request,
                response=resp,
            )

        # Parse time series data
        bars = self._parse_time_series(data, symbol, resolution, start, end)

        logger.info("alphavantage_fetch_complete", symbol=symbol, bars=len(bars))

        return AdapterResult(
            bars=bars,
            raw_response=raw_bytes,
            source=self.source_name,
            endpoint=f"/query?function={function}&symbol={symbol}",
            symbols_requested=[symbol],
            request_time=datetime.now(tz=UTC),
        )

    def _parse_time_series(
        self,
        data: dict[str, Any],
        symbol: str,
        resolution: str,
        start: date,
        end: date,
    ) -> list[BarRecord]:
        """Parse Alpha Vantage time series response into BarRecords."""
        # Find the time series key (varies by function)
        ts_key = None
        for key in data:
            if "Time Series" in key:
                ts_key = key
                break

        if not ts_key:
            return []

        time_series = data[ts_key]
        bars: list[BarRecord] = []

        for date_str, values in time_series.items():
            # Parse date (format varies: "2024-01-15" for daily, "2024-01-15 16:00:00" for intraday)
            try:
                if " " in date_str:
                    ts = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                else:
                    dt = date.fromisoformat(date_str)
                    ts = datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
            except ValueError:
                continue

            bar_date = ts.date()
            if bar_date < start or bar_date > end:
                continue

            # Alpha Vantage keys have numeric prefixes like "1. open"
            bars.append(
                BarRecord(
                    symbol=symbol,
                    ts=ts,
                    resolution=resolution,
                    open=Decimal(values.get("1. open", "0")),
                    high=Decimal(values.get("2. high", "0")),
                    low=Decimal(values.get("3. low", "0")),
                    close=Decimal(values.get("4. close", "0")),
                    volume=int(values.get("5. volume", 0)) or None,
                    vwap=None,
                    trades=None,
                )
            )

        # Sort by timestamp
        bars.sort(key=lambda b: b.ts)
        return bars

    @staticmethod
    def _resolve_function(resolution: str) -> tuple[str, str | None]:
        """Map resolution to Alpha Vantage function name and interval param."""
        if resolution in ("1m", "5m", "15m", "30m", "1h"):
            interval_map = {
                "1m": "1min",
                "5m": "5min",
                "15m": "15min",
                "30m": "30min",
                "1h": "60min",
            }
            return "TIME_SERIES_INTRADAY", interval_map[resolution]
        if resolution == "1wk":
            return "TIME_SERIES_WEEKLY", None
        if resolution == "1mo":
            return "TIME_SERIES_MONTHLY", None
        return "TIME_SERIES_DAILY", None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
