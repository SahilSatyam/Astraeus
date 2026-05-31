"""Tests for the kill switch manager (in-process state, no Redis required)."""

from __future__ import annotations

from astraeus_trading.kill_switch import KillSwitchManager


class TestKillSwitchManager:
    """Unit tests for KillSwitchManager in-process state (no Redis)."""

    def test_initial_state_not_armed(self) -> None:
        ks = KillSwitchManager()
        assert not ks.is_armed("global")
        assert not ks.is_armed("account:test")

    def test_load_from_db(self) -> None:
        ks = KillSwitchManager()
        ks.load_from_db({"global": True, "strategy:momentum": False})
        assert ks.is_armed("global")
        assert not ks.is_armed("strategy:momentum")

    def test_is_any_armed_none(self) -> None:
        ks = KillSwitchManager()
        result = ks.is_any_armed(["global", "account:test", "strategy:x"])
        assert result is None

    def test_is_any_armed_returns_first(self) -> None:
        ks = KillSwitchManager()
        ks.load_from_db({"strategy:x": True, "global": False})
        result = ks.is_any_armed(["global", "account:test", "strategy:x"])
        assert result == "strategy:x"

    def test_is_any_armed_global_priority(self) -> None:
        ks = KillSwitchManager()
        ks.load_from_db({"global": True, "strategy:x": True})
        result = ks.is_any_armed(["global", "strategy:x"])
        assert result == "global"
