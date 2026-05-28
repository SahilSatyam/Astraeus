"""Alpaca WebSocket streaming adapter.

Connects to Alpaca's real-time market data stream for live bar/trade/quote
updates. Uses the IEX feed (free tier) or SIP feed (paid).

The stream runs as a long-lived async task, pushing received bars into
a callback or asyncio.Queue for downstream processing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

import structlog

from astraeus_marketdata.adapters.base import BarRecord

logger = structlog.get_logger("astraeus.marketdata.alpaca_ws")

_WS_URL_IEX = "wss://stream.data.alpaca.markets/v2/iex"
_WS_URL_SIP = "wss://stream.data.alpaca.markets/v2/sip"


class StreamFeed(str, Enum):
    """Alpaca data feed selection."""

    IEX = "iex"
    SIP = "sip"


class BarCallback(Protocol):
    """Protocol for bar reception callbacks."""

    async def __call__(self, bar: BarRecord) -> None: ...


class AlpacaStreamClient:
    """WebSocket streaming client for Alpaca real-time market data.

    Usage:
        client = AlpacaStreamClient(api_key, api_secret)
        await client.subscribe_bars(["SPY", "AAPL", "MSFT"])
        await client.start(on_bar=my_callback)
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        feed: StreamFeed = StreamFeed.IEX,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._feed = feed
        self._ws_url = _WS_URL_SIP if feed == StreamFeed.SIP else _WS_URL_IEX
        self._subscribed_bars: list[str] = []
        self._ws: Any = None
        self._running = False
        self._stop_event = asyncio.Event()
        self._on_bar: BarCallback | None = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

    async def subscribe_bars(self, symbols: list[str]) -> None:
        """Set symbols to subscribe to for minute bar updates."""
        self._subscribed_bars = symbols
        # If already connected, send subscription message
        if self._ws is not None:
            await self._send_subscribe()

    async def start(
        self,
        on_bar: BarCallback | None = None,
        queue: asyncio.Queue[BarRecord] | None = None,
    ) -> None:
        """Start the streaming connection. Blocks until stop() is called.

        Provide either on_bar callback or queue (not both).
        Reconnects automatically on disconnection with exponential backoff.
        """
        self._on_bar = on_bar
        self._queue = queue
        self._running = True
        self._stop_event.clear()

        while self._running and not self._stop_event.is_set():
            try:
                await self._connect_and_stream()
            except Exception as exc:
                if not self._running:
                    break
                logger.warning(
                    "alpaca_ws_disconnected",
                    error=str(exc),
                    reconnect_delay=self._reconnect_delay,
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

        logger.info("alpaca_ws_stopped")

    async def stop(self) -> None:
        """Gracefully stop the streaming connection."""
        self._running = False
        self._stop_event.set()
        if self._ws is not None:
            await self._ws.close()

    async def _connect_and_stream(self) -> None:
        """Establish connection, authenticate, subscribe, and process messages."""
        try:
            import websockets
        except ImportError as exc:
            raise ImportError(
                "websockets package required for streaming. Install with: pip install websockets"
            ) from exc

        logger.info("alpaca_ws_connecting", url=self._ws_url, feed=self._feed.value)

        async with websockets.connect(self._ws_url) as ws:
            self._ws = ws
            self._reconnect_delay = 1.0  # Reset on successful connect

            # Wait for welcome message
            welcome = await ws.recv()
            welcome_data = json.loads(welcome)
            logger.debug("alpaca_ws_welcome", data=welcome_data)

            # Authenticate
            await self._authenticate(ws)

            # Subscribe to bars
            if self._subscribed_bars:
                await self._send_subscribe()

            logger.info(
                "alpaca_ws_connected",
                feed=self._feed.value,
                symbols=len(self._subscribed_bars),
            )

            # Process messages
            async for message in ws:
                if self._stop_event.is_set():
                    break
                await self._handle_message(message)

    async def _authenticate(self, ws: Any) -> None:
        """Send authentication message."""
        auth_msg = json.dumps(
            {
                "action": "auth",
                "key": self._api_key,
                "secret": self._api_secret,
            }
        )
        await ws.send(auth_msg)

        # Wait for auth response
        resp = await ws.recv()
        resp_data = json.loads(resp)

        if isinstance(resp_data, list):
            for msg in resp_data:
                if msg.get("T") == "error":
                    raise ConnectionError(f"Alpaca auth failed: {msg.get('msg', 'unknown error')}")
                if msg.get("T") == "success" and msg.get("msg") == "authenticated":
                    logger.info("alpaca_ws_authenticated")
                    return

        raise ConnectionError("Unexpected auth response")

    async def _send_subscribe(self) -> None:
        """Send subscription message for bars."""
        if self._ws is None:
            return

        sub_msg = json.dumps(
            {
                "action": "subscribe",
                "bars": self._subscribed_bars,
            }
        )
        await self._ws.send(sub_msg)
        logger.info("alpaca_ws_subscribed", symbols=self._subscribed_bars)

    async def _handle_message(self, raw_message: str | bytes) -> None:
        """Parse and dispatch a WebSocket message."""
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode()

        try:
            messages = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning("alpaca_ws_invalid_json", raw=raw_message[:200])
            return

        if not isinstance(messages, list):
            messages = [messages]

        for msg in messages:
            msg_type = msg.get("T")

            if msg_type == "b":
                # Minute bar
                await self._process_bar(msg)
            elif msg_type == "error":
                logger.error("alpaca_ws_error", code=msg.get("code"), message=msg.get("msg"))
            elif msg_type == "subscription":
                logger.debug("alpaca_ws_subscription_confirmed", bars=msg.get("bars", []))

    async def _process_bar(self, msg: dict[str, Any]) -> None:
        """Convert a raw bar message to BarRecord and dispatch."""
        try:
            ts = datetime.fromisoformat(msg["t"].replace("Z", "+00:00"))
            bar = BarRecord(
                symbol=msg["S"],
                ts=ts,
                resolution="1m",
                open=Decimal(str(msg["o"])),
                high=Decimal(str(msg["h"])),
                low=Decimal(str(msg["l"])),
                close=Decimal(str(msg["c"])),
                volume=msg.get("v"),
                vwap=Decimal(str(msg["vw"])) if msg.get("vw") else None,
                trades=msg.get("n"),
            )
        except (KeyError, ValueError) as exc:
            logger.warning("alpaca_ws_bar_parse_error", error=str(exc), msg=msg)
            return

        # Dispatch to callback or queue
        if self._on_bar is not None:
            await self._on_bar(bar)
        elif self._queue is not None:
            await self._queue.put(bar)

        logger.debug("alpaca_ws_bar_received", symbol=bar.symbol, ts=str(bar.ts))
