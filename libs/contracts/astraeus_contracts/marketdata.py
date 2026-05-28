"""Market data event contracts (schema registry).

Defines the canonical schemas for all market data events flowing through
Redpanda topics. These serve as the schema registry — all producers and
consumers agree on these structures.

Schema versioning:
- Each schema has a SCHEMA_VERSION constant
- Breaking changes increment the major version and create a new topic
- Additive changes (new optional fields) increment minor version in-place
- The schema_version field in each event enables consumers to handle
  multiple versions during rolling upgrades

Topic naming convention:
  md.{asset_class}.{resolution}.v{version}
  e.g., md.equity.daily.v1, md.equity.minute.v1, md.macro.daily.v1
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# --- Enums ---


class AssetClass(str, Enum):
    """Supported asset classes."""

    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"
    MACRO = "macro"
    CRYPTO = "crypto"


class Resolution(str, Enum):
    """Supported bar resolutions."""

    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    HOUR_1 = "1h"
    DAY_1 = "1d"
    WEEK_1 = "1wk"


class DataSource(str, Enum):
    """Known data sources."""

    YAHOO = "yahoo"
    POLYGON = "polygon"
    ALPACA = "alpaca"
    ALPHAVANTAGE = "alphavantage"
    FRED = "fred"


# --- Bar Events ---

BARS_SCHEMA_VERSION = 1


class BarEvent(BaseModel):
    """Canonical bar event schema for Redpanda topics.

    Topic: md.equity.{resolution}.v1
    Key: symbol (bytes)
    """

    schema_version: int = Field(
        default=BARS_SCHEMA_VERSION, description="Schema version for evolution"
    )
    symbol: str = Field(..., max_length=32, description="Ticker symbol")
    ts: datetime = Field(..., description="Bar timestamp (UTC)")
    resolution: Resolution = Field(..., description="Bar resolution")
    open: Decimal = Field(..., decimal_places=8, description="Open price")
    high: Decimal = Field(..., decimal_places=8, description="High price")
    low: Decimal = Field(..., decimal_places=8, description="Low price")
    close: Decimal = Field(..., decimal_places=8, description="Close price")
    volume: int | None = Field(default=None, description="Volume")
    vwap: Decimal | None = Field(default=None, decimal_places=8, description="VWAP")
    trades: int | None = Field(default=None, description="Number of trades")
    source: DataSource = Field(..., description="Data source")
    run_id: str = Field(..., description="Ingestion run UUID")


# --- Fundamental Events ---

FUNDAMENTALS_SCHEMA_VERSION = 1


class FundamentalEvent(BaseModel):
    """Fundamental data event (earnings, financials, etc.).

    Topic: md.fundamentals.v1
    Key: symbol (bytes)
    """

    schema_version: int = Field(default=FUNDAMENTALS_SCHEMA_VERSION)
    symbol: str = Field(..., max_length=32)
    report_date: datetime = Field(..., description="Report/filing date")
    period: str = Field(..., description="Fiscal period (Q1, Q2, Q3, Q4, FY)")
    metric_name: str = Field(..., description="Metric identifier (e.g., revenue, eps)")
    value: Decimal = Field(..., description="Metric value")
    currency: str = Field(default="USD", max_length=3)
    source: DataSource = Field(...)
    run_id: str = Field(...)


# --- Macro Events ---

MACRO_SCHEMA_VERSION = 1


class MacroEvent(BaseModel):
    """Macro economic data event (FRED series, etc.).

    Topic: md.macro.daily.v1
    Key: series_id (bytes)
    """

    schema_version: int = Field(default=MACRO_SCHEMA_VERSION)
    series_id: str = Field(..., max_length=32, description="FRED series ID or equivalent")
    ts: datetime = Field(..., description="Observation timestamp (UTC)")
    value: Decimal = Field(..., description="Observation value")
    source: DataSource = Field(default=DataSource.FRED)
    run_id: str = Field(...)


# --- Corporate Action Events ---

CORPORATE_ACTION_SCHEMA_VERSION = 1


class CorporateActionType(str, Enum):
    """Types of corporate actions."""

    SPLIT = "split"
    DIVIDEND = "dividend"
    SPINOFF = "spinoff"
    MERGER = "merger"


class CorporateActionEvent(BaseModel):
    """Corporate action event.

    Topic: md.corporate_actions.v1
    Key: symbol (bytes)
    """

    schema_version: int = Field(default=CORPORATE_ACTION_SCHEMA_VERSION)
    symbol: str = Field(..., max_length=32)
    action_type: CorporateActionType = Field(...)
    ex_date: str = Field(..., description="Ex-date in ISO format")
    ratio: Decimal | None = Field(default=None, description="Split ratio (e.g., 7 for 7:1)")
    cash_amount: Decimal | None = Field(default=None, description="Dividend amount per share")
    currency: str = Field(default="USD", max_length=3)
    source: DataSource = Field(...)
    run_id: str = Field(...)
    raw_payload: dict[str, Any] | None = Field(default=None, description="Original source payload")


# --- DLQ Events ---

DLQ_SCHEMA_VERSION = 1


class DLQEvent(BaseModel):
    """Dead letter queue event for failed ingestion records.

    Topic: md.dlq.v1
    Key: original_key (bytes)
    """

    schema_version: int = Field(default=DLQ_SCHEMA_VERSION)
    dlq_id: str = Field(..., description="Unique DLQ entry ID")
    original_topic: str = Field(..., description="Topic the message was destined for")
    original_key: str | None = Field(default=None)
    payload: dict[str, Any] = Field(..., description="Original message payload")
    error_type: str = Field(..., description="Exception class name")
    error_message: str = Field(..., description="Error description")
    source: DataSource = Field(...)
    run_id: str | None = Field(default=None)
    attempt_count: int = Field(default=1)
    failed_at: datetime = Field(...)


# --- Schema Registry ---

SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "md.equity.daily.v1": BarEvent,
    "md.equity.minute.v1": BarEvent,
    "md.macro.daily.v1": MacroEvent,
    "md.fundamentals.v1": FundamentalEvent,
    "md.corporate_actions.v1": CorporateActionEvent,
    "md.dlq.v1": DLQEvent,
}


def get_schema_for_topic(topic: str) -> type[BaseModel] | None:
    """Look up the schema class for a given topic name."""
    return SCHEMA_REGISTRY.get(topic)


def validate_event(topic: str, payload: dict[str, Any]) -> BaseModel:
    """Validate a payload against the registered schema for a topic.

    Raises:
        ValueError: If topic has no registered schema.
        pydantic.ValidationError: If payload doesn't match schema.
    """
    schema = get_schema_for_topic(topic)
    if schema is None:
        raise ValueError(f"No schema registered for topic: {topic}")
    return schema.model_validate(payload)
