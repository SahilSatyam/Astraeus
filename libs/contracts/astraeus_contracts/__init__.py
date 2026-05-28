"""Astraeus shared DTOs."""

from astraeus_contracts.health import (
    HealthResponse,
    HealthStatus,
    ReadinessCheck,
    ReadinessResponse,
    VersionResponse,
)
from astraeus_contracts.marketdata import (
    SCHEMA_REGISTRY,
    AssetClass,
    BarEvent,
    CorporateActionEvent,
    CorporateActionType,
    DataSource,
    DLQEvent,
    FundamentalEvent,
    MacroEvent,
    Resolution,
    get_schema_for_topic,
    validate_event,
)
from astraeus_contracts.problem import ProblemDetails

__all__ = [
    "SCHEMA_REGISTRY",
    "AssetClass",
    "BarEvent",
    "CorporateActionEvent",
    "CorporateActionType",
    "DLQEvent",
    "DataSource",
    "FundamentalEvent",
    "HealthResponse",
    "HealthStatus",
    "MacroEvent",
    "ProblemDetails",
    "ReadinessCheck",
    "ReadinessResponse",
    "Resolution",
    "VersionResponse",
    "get_schema_for_topic",
    "validate_event",
]
