"""Canonical stream name builders.

Provides type-safe stream name construction following the naming policy:
  md.{asset_class}.{resolution_or_type}.v{version}

See TOPIC_NAMING.md for the full policy document.
"""

from __future__ import annotations

from astraeus_contracts.marketdata import AssetClass, Resolution


def bar_topic(asset_class: AssetClass | str, resolution: Resolution | str, version: int = 1) -> str:
    """Build a bar topic name.

    Examples:
        bar_topic(AssetClass.EQUITY, Resolution.DAY_1) -> "md.equity.daily.v1"
        bar_topic("equity", "1m") -> "md.equity.minute.v1"
    """
    res_str = str(resolution)
    timeframe = _resolution_to_timeframe(res_str)
    return f"md.{asset_class}.{timeframe}.v{version}"


def tick_topic(asset_class: AssetClass | str = AssetClass.EQUITY, version: int = 1) -> str:
    """Build a tick topic name.

    Example:
        tick_topic() -> "md.equity.tick.v1"
    """
    return f"md.{asset_class}.tick.v{version}"


def macro_topic(version: int = 1) -> str:
    """Build the macro series topic name.

    Example:
        macro_topic() -> "md.macro.daily.v1"
    """
    return f"md.macro.daily.v{version}"


def corporate_action_topic(version: int = 1) -> str:
    """Build the corporate actions topic name.

    Example:
        corporate_action_topic() -> "md.corporate_actions.v1"
    """
    return f"md.corporate_actions.v{version}"


def fundamentals_topic(version: int = 1) -> str:
    """Build the fundamentals topic name.

    Example:
        fundamentals_topic() -> "md.fundamentals.v1"
    """
    return f"md.fundamentals.v{version}"


def dlq_topic(source: str | None = None, version: int = 1) -> str:
    """Build a DLQ topic name.

    Examples:
        dlq_topic() -> "md.dlq.v1"
        dlq_topic("polygon") -> "md.dlq.polygon.v1"
    """
    if source:
        return f"md.dlq.{source}.v{version}"
    return f"md.dlq.v{version}"


def _resolution_to_timeframe(resolution: str) -> str:
    """Map resolution string to topic timeframe segment."""
    if resolution in ("1d", "1wk"):
        return "daily"
    if resolution in ("1m", "5m", "15m"):
        return "minute"
    if resolution == "1h":
        return "hourly"
    return "daily"
