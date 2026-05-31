"""Kill switch service with Redis pub/sub for sub-second propagation.

Architecture:
- Each OMS/EMS process subscribes to a Redis pub/sub channel.
- When a kill switch is armed/disarmed, the change is published.
- Each process maintains an in-process flag (no DB call per order).
- The hot-path cost is one dict lookup; propagation is one Redis publish.

Target: sub-1-second end-to-end from arm to rejection of new orders.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

KILL_SWITCH_CHANNEL = "astraeus:kill_switch"


class KillSwitchManager:
    """In-process kill switch state with Redis pub/sub propagation.

    Usage::

        ks = KillSwitchManager(redis_url="redis://localhost:6379/0")
        await ks.start()

        # Check before submitting an order
        if ks.is_armed("global"):
            raise KillSwitchActive("global")

        # Arm from any process
        await ks.arm("global", armed_by="operator", reason="maintenance")

        # Cleanup
        await ks.stop()
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._state: dict[str, bool] = {}
        self._subscriber_task: asyncio.Task[None] | None = None
        self._redis: Any = None
        self._pubsub: Any = None

    def is_armed(self, scope: str) -> bool:
        """Check if a kill switch is armed. O(1) dict lookup."""
        return self._state.get(scope, False)

    def is_any_armed(self, scopes: list[str]) -> str | None:
        """Check if any of the given scopes is armed. Returns first armed scope or None."""
        for scope in scopes:
            if self._state.get(scope, False):
                return scope
        return None

    async def arm(self, scope: str, armed_by: str = "system", reason: str = "") -> None:
        """Arm a kill switch and publish to all subscribers."""
        self._state[scope] = True
        await self._publish(
            action="arm",
            scope=scope,
            armed_by=armed_by,
            reason=reason,
        )
        logger.warning(
            "Kill switch armed",
            extra={"scope": scope, "armed_by": armed_by, "reason": reason},
        )

    async def disarm(self, scope: str, disarmed_by: str = "system", reason: str = "") -> None:
        """Disarm a kill switch and publish to all subscribers."""
        self._state[scope] = False
        await self._publish(
            action="disarm",
            scope=scope,
            armed_by=disarmed_by,
            reason=reason,
        )
        logger.info(
            "Kill switch disarmed",
            extra={"scope": scope, "disarmed_by": disarmed_by, "reason": reason},
        )

    async def start(self) -> None:
        """Connect to Redis and start listening for kill switch events."""
        try:
            import redis.asyncio as aioredis
        except ImportError as e:
            msg = "redis[asyncio] is required for KillSwitchManager"
            raise ImportError(msg) from e

        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(KILL_SWITCH_CHANNEL)
        self._subscriber_task = asyncio.create_task(self._listen())
        logger.info("Kill switch manager started, subscribed to Redis pub/sub")

    async def stop(self) -> None:
        """Stop listening and disconnect."""
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe(KILL_SWITCH_CHANNEL)
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        logger.info("Kill switch manager stopped")

    async def _publish(self, **kwargs: Any) -> None:
        """Publish a kill switch event to Redis."""
        if self._redis is None:
            return
        payload = {**kwargs, "ts": datetime.now(timezone.utc).isoformat()}
        await self._redis.publish(KILL_SWITCH_CHANNEL, json.dumps(payload))

    async def _listen(self) -> None:
        """Listen for kill switch events from Redis pub/sub."""
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    scope = data["scope"]
                    action = data["action"]
                    if action == "arm":
                        self._state[scope] = True
                    elif action == "disarm":
                        self._state[scope] = False
                    logger.debug(
                        "Kill switch event received",
                        extra={"scope": scope, "action": action},
                    )
                except (json.JSONDecodeError, KeyError):
                    logger.warning("Invalid kill switch message", extra={"raw": message})
        except asyncio.CancelledError:
            pass

    def load_from_db(self, states: dict[str, bool]) -> None:
        """Bulk-load kill switch states from DB on startup."""
        self._state.update(states)
