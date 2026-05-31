"""Unit tests for the persistence module."""

from __future__ import annotations

import asyncio

from astraeus_agent_runtime.persistence import _json_dumps, load_run, persist_run


class TestJsonDumps:
    """Test JSON serialization helper."""

    def test_none_returns_none(self) -> None:
        assert _json_dumps(None) is None

    def test_dict_serializes(self) -> None:
        result = _json_dumps({"ticker": "AAPL", "value": 42.5})
        assert '"ticker"' in result
        assert '"AAPL"' in result

    def test_nested_dict(self) -> None:
        result = _json_dumps({"a": {"b": [1, 2, 3]}})
        assert result is not None
        assert "[1, 2, 3]" in result


class TestPersistenceInterface:
    """Test that persistence functions are async."""

    def test_persist_run_is_coroutine(self) -> None:
        assert asyncio.iscoroutinefunction(persist_run)

    def test_load_run_is_coroutine(self) -> None:
        assert asyncio.iscoroutinefunction(load_run)
