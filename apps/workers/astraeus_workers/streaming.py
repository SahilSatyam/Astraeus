"""Streaming ingestion worker.

Connects to Alpaca WebSocket for real-time minute bars and persists them
through the same ingestion pipeline (dedup → write → outbox → lineage).

Runs as a long-lived async task within the workers service.
"""

from __future__ import annotations

import asyncio

import structlog
from astraeus_marketdata.adapters.alpaca_ws import AlpacaStreamClient, StreamFeed
from astraeus_marketdata.adapters.base import BarRecord, compute_payload_hash
from astraeus_marketdata.models import MarketBarRaw, Outbox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger("astraeus.workers.streaming")

# Default symbols to stream (can be overridden via config)
_DEFAULT_STREAM_SYMBOLS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT"]

_TOPIC = "md.equity.minute.v1"


class StreamingWorker:
    """Manages the WebSocket streaming connection and bar persistence."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        api_key: str,
        api_secret: str,
        symbols: list[str] | None = None,
        feed: StreamFeed = StreamFeed.IEX,
    ) -> None:
        self._session_factory = session_factory
        self._client = AlpacaStreamClient(
            api_key=api_key,
            api_secret=api_secret,
            feed=feed,
        )
        self._symbols = symbols or _DEFAULT_STREAM_SYMBOLS
        self._queue: asyncio.Queue[BarRecord] = asyncio.Queue(maxsize=10000)
        self._stop_event = asyncio.Event()
        self._bars_received = 0
        self._bars_persisted = 0

    async def start(self) -> None:
        """Start streaming and persistence tasks."""
        logger.info(
            "streaming_worker_start",
            symbols=self._symbols,
        )

        await self._client.subscribe_bars(self._symbols)

        # Run stream reader and DB writer concurrently
        await asyncio.gather(
            self._client.start(queue=self._queue),
            self._persist_loop(),
        )

    async def stop(self) -> None:
        """Gracefully stop the streaming worker."""
        self._stop_event.set()
        await self._client.stop()
        logger.info(
            "streaming_worker_stopped",
            bars_received=self._bars_received,
            bars_persisted=self._bars_persisted,
        )

    async def _persist_loop(self) -> None:
        """Drain the queue and persist bars in micro-batches."""
        batch: list[BarRecord] = []
        batch_timeout = 1.0  # Flush every second or when batch is full
        max_batch_size = 50

        while not self._stop_event.is_set():
            try:
                # Collect bars from queue
                try:
                    bar = await asyncio.wait_for(self._queue.get(), timeout=batch_timeout)
                    batch.append(bar)
                    self._bars_received += 1

                    # Drain any additional available bars
                    while len(batch) < max_batch_size:
                        try:
                            bar = self._queue.get_nowait()
                            batch.append(bar)
                            self._bars_received += 1
                        except asyncio.QueueEmpty:
                            break

                except TimeoutError:
                    pass

                # Flush batch if we have bars
                if batch:
                    await self._flush_batch(batch)
                    batch = []

            except Exception:
                logger.exception("streaming_persist_error")
                batch = []
                await asyncio.sleep(1.0)

    async def _flush_batch(self, bars: list[BarRecord]) -> None:
        """Persist a batch of bars to the database."""
        import json
        import uuid

        run_id = uuid.uuid4()

        async with self._session_factory() as session:
            for bar in bars:
                payload_hash = compute_payload_hash(bar, "alpaca")

                # Idempotency check
                from sqlalchemy import select

                existing = await session.execute(
                    select(MarketBarRaw.symbol).where(
                        MarketBarRaw.symbol == bar.symbol,
                        MarketBarRaw.ts == bar.ts,
                        MarketBarRaw.resolution == bar.resolution,
                        MarketBarRaw.source == "alpaca",
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                bar_row = MarketBarRaw(
                    symbol=bar.symbol,
                    ts=bar.ts,
                    resolution=bar.resolution,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    vwap=bar.vwap,
                    trades=bar.trades,
                    source="alpaca",
                    schema_version=1,
                    ingest_run_id=run_id,
                    payload_hash=payload_hash,
                )
                session.add(bar_row)

                # Outbox entry
                outbox_payload = json.dumps(
                    {
                        "symbol": bar.symbol,
                        "ts": bar.ts.isoformat(),
                        "resolution": bar.resolution,
                        "open": str(bar.open),
                        "high": str(bar.high),
                        "low": str(bar.low),
                        "close": str(bar.close),
                        "volume": bar.volume,
                        "source": "alpaca",
                        "run_id": str(run_id),
                    }
                ).encode()

                session.add(
                    Outbox(
                        topic=_TOPIC,
                        key=bar.symbol.encode(),
                        payload=outbox_payload,
                        headers={"source": "alpaca", "run_id": str(run_id)},
                    )
                )

                self._bars_persisted += 1

            await session.commit()

        if bars:
            logger.debug(
                "streaming_batch_flushed",
                bars=len(bars),
                persisted=self._bars_persisted,
            )
