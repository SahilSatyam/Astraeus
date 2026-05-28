"""Yahoo Finance adapter via yfinance.

Used as the primary free historical data source for daily OHLCV bars.
Unreliable for production but sufficient for personal use and cross-checks.

Note: yfinance is synchronous under the hood; we run it in a thread executor
to avoid blocking the async event loop.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import structlog
import yfinance as yf

from astraeus_marketdata.adapters.base import AdapterResult, BarRecord, BaseAdapter

logger = structlog.get_logger("astraeus.marketdata.yahoo")


class YahooAdapter(BaseAdapter):
    """Fetch historical bars from Yahoo Finance."""

    source_name = "yahoo"

    async def fetch_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        resolution: str = "1d",
    ) -> list[AdapterResult]:
        """Fetch daily bars for each symbol individually.

        yfinance supports batch downloads but per-symbol gives cleaner
        error isolation and lineage tracking.
        """
        results: list[AdapterResult] = []
        for symbol in symbols:
            result = await self._fetch_single(symbol, start, end, resolution)
            results.append(result)
        return results

    async def _fetch_single(
        self,
        symbol: str,
        start: date,
        end: date,
        resolution: str,
    ) -> AdapterResult:
        """Fetch bars for a single symbol in a thread executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_sync, symbol, start, end, resolution)

    def _fetch_sync(
        self,
        symbol: str,
        start: date,
        end: date,
        resolution: str,
    ) -> AdapterResult:
        """Synchronous fetch — runs in executor."""
        interval_map = {"1d": "1d", "1h": "1h", "1m": "1m", "1wk": "1wk"}
        yf_interval = interval_map.get(resolution, "1d")

        logger.debug("yahoo_fetch_start", symbol=symbol, start=str(start), end=str(end))

        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start.isoformat(),
            end=end.isoformat(),
            interval=yf_interval,
            auto_adjust=False,
            actions=False,
        )

        if df.empty:
            logger.warning("yahoo_empty_response", symbol=symbol)
            return AdapterResult(
                bars=[],
                raw_response=b"{}",
                source=self.source_name,
                endpoint=f"yfinance.Ticker({symbol}).history",
                symbols_requested=[symbol],
            )

        # Build raw response bytes for archival
        raw_data: dict[str, Any] = {
            "symbol": symbol,
            "rows": len(df),
            "columns": list(df.columns),
            "index_start": str(df.index[0]),
            "index_end": str(df.index[-1]),
        }
        raw_bytes = json.dumps(raw_data, default=str).encode()

        bars: list[BarRecord] = []
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime()  # type: ignore[union-attr]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            bars.append(
                BarRecord(
                    symbol=symbol,
                    ts=ts,
                    resolution=resolution,
                    open=Decimal(str(row["Open"])),
                    high=Decimal(str(row["High"])),
                    low=Decimal(str(row["Low"])),
                    close=Decimal(str(row["Close"])),
                    volume=int(row["Volume"]) if row["Volume"] else None,
                    vwap=None,
                    trades=None,
                )
            )

        logger.info("yahoo_fetch_complete", symbol=symbol, bars=len(bars))
        return AdapterResult(
            bars=bars,
            raw_response=raw_bytes,
            source=self.source_name,
            endpoint=f"yfinance.Ticker({symbol}).history",
            symbols_requested=[symbol],
            request_time=datetime.now(tz=UTC),
        )

    async def close(self) -> None:
        """No persistent resources to release."""
