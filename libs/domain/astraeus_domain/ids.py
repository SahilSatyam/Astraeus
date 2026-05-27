"""Typed IDs.

These are `NewType` aliases of `str` so the type checker catches mixing IDs from
different domains while runtime stays a plain string. Prefer these to bare
``str`` in function signatures whenever an identifier crosses a module boundary.
"""

from __future__ import annotations

from typing import NewType

AccountId = NewType("AccountId", str)
OrderId = NewType("OrderId", str)
RunId = NewType("RunId", str)
StrategyId = NewType("StrategyId", str)
Symbol = NewType("Symbol", str)
