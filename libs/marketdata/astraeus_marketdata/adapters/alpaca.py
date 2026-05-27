"""Alpaca Market Data adapter.

Primary source for historical bars (free tier includes daily + 1m bars back to 2016).
Also used for streaming in Phase 1 week 5.

Requires ALPACA_API_KEY and ALPACA_API_SECRET environment variables.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import structlog

from astraeus_marketdata.adapters.base import AdapterResult, BarRecord, BaseAdapter
from astraeus_marketdata.ratelimit import RateLimiter
from astraeus_marketdata.retry import retry_with_backoff

logger = structlog.get_logger("astraeus.marketdata.alpaca")

# Alpaca free tier: 200 requests/minute
_RATE_LIMIT = RateLimiter(rate=200, period=60.0)

_BASE_URL = "https://data.alpaca.markets/v2"


class AlpacaAdapter(BaseAdapter):
    """Fetch historical bars from Alpaca Market Data API."""

    source_name = "alpaca"

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
            },
            timeout=30.0,
        )

    async def fetch_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        resolution: str = "1d",
    ) -> list[AdapterResult]:
        """Fetch bars for multiple symbols via Alpaca's multi-bar endpoint."""
        results: list[AdapterResult] = []
        # Alpaca supports up to 200 symbols per request but we batch by 50
        # for cleaner error isolation
        batch_size = 50
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            result = await self._fetch_batch(batch, start, end, resolution)
            results.append(result)
        return results

    @retry_with_backoff(
        max_attempts=3,
        base_delay=2.0,
        retryable_exceptions=(httpx.HTTPStatusError, httpx.TransportError),
    )
    async def _fetch_batch(
        self,
        symbols: list[str],
        start: date,
        end: date,
        resolution: str,
    ) -> AdapterResult:
        """Fetch a batch of symbols with pagination support."""
        timeframe_map = {"1d": "1Day", "1h": "1Hour", "1m": "1Min"}
        timeframe = timeframe_map.get(resolution, "1Day")

        all_bars: list[BarRecord] = []
        raw_responses: list[bytes] = []
        page_token: str | None = None

        while True:
            await _RATE_LIMIT.acquire()

            params: dict[str, str] = {
                "symbols": ",".join(symbols),
                "timeframe": timeframe,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": "10000",
                "adjustment": "raw",
                "feed": "iex",
            }
            if page_token:
                params["page_token"] = page_token

            logger.debug(
                "alpaca_fetch",
                symbols_count=len(symbols),
                start=str(start),
                end=str(end),
                page_token=page_token,
            )

            resp = await self._client.get("/stocks/bars", params=params)
            resp.raise_for_status()

            raw_bytes = resp.content
            raw_responses.append(raw_bytes)
            data = resp.json()

            bars_data = data.get("bars", {})
            for symbol, symbol_bars in bars_data.items():
                for bar in symbol_bars:
                    ts = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
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

            page_token = data.get("next_page_token")
            if not page_token:
                break

        logger.info(
            "alpaca_fetch_complete",
            symbols_count=len(symbols),
            bars=len(all_bars),
            pages=len(raw_responses),
        )

        # Concatenate raw responses for archival
        combined_raw = b"\n".join(raw_responses)

        return AdapterResult(
            bars=all_bars,
            raw_response=combined_raw,
            source=self.source_name,
            endpoint="/v2/stocks/bars",
            symbols_requested=symbols,
            request_time=datetime.now(tz=timezone.utc),
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
