"""Feature Definition DSL.

Researchers declare features using this DSL. Each definition produces:
1. A feature registry entry (metadata + definition hash)
2. A table name following the canonical bitemporal shape
3. A materialization plan (SQL transform)
4. A PIT-correct retrieval view

Usage:
    from astraeus_features.dsl import FeatureDefinition, Entity, sql_transform

    momentum_20d = FeatureDefinition(
        name="momentum_20d",
        group="price_derived",
        entity=Entity.SYMBOL,
        dtype="numeric",
        description="20 trading day price momentum, log return.",
        dependencies=["ohlcv_daily"],
        freshness_sla=timedelta(hours=2),
        knowledge_lag=timedelta(0),
        materialization="incremental",
        transform=sql_transform("SELECT ..."),
        owner="quant-research",
        tags=["factor", "momentum"],
    )
"""

from __future__ import annotations

import hashlib
import re
import textwrap
from datetime import timedelta
from enum import StrEnum
from typing import Any


class Entity(StrEnum):
    """Entity types for feature definitions."""

    SYMBOL = "symbol"
    UNIVERSE = "universe"
    MACRO = "macro"


class MaterializationMode(StrEnum):
    """How the feature is materialized."""

    INCREMENTAL = "incremental"
    FULL = "full"
    ON_DEMAND = "on_demand"


def sql_transform(sql: str) -> str:
    """Wrap a SQL transform for the DSL.

    The SQL should reference upstream tables and use :as_of as a parameter
    for PIT-correctness. It must produce columns:
    (symbol, event_ts, knowledge_ts, value, value_version)
    """
    return textwrap.dedent(sql).strip()


def _canonicalize_sql(sql: str) -> str:
    """Normalize SQL for deterministic hashing.

    Strips comments, collapses whitespace, lowercases keywords.
    This prevents trivial reformatting from changing the definition hash.
    """
    # Remove SQL comments
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    # Collapse whitespace
    sql = re.sub(r"\s+", " ", sql).strip()
    return sql.lower()


def _compute_definition_hash(
    name: str,
    transform: str,
    dependencies: list[str],
    dtype: str,
) -> str:
    """Compute deterministic hash for a feature definition.

    Same logic + same deps + same dtype = same hash. Reformatting SQL
    doesn't change the hash thanks to canonicalization.
    """
    canonical_sql = _canonicalize_sql(transform)
    canonical = f"{name}|{canonical_sql}|{','.join(sorted(dependencies))}|{dtype}"
    return hashlib.sha256(canonical.encode()).hexdigest()


class FeatureDefinition:
    """A single feature definition.

    This is the core DSL object. Researchers create instances of this class
    to define features. The platform uses these definitions to:
    - Create the storage table
    - Register in the feature catalog
    - Generate materialization flows
    - Build PIT-correct retrieval views
    """

    def __init__(
        self,
        name: str,
        group: str,
        transform: str,
        *,
        entity: Entity = Entity.SYMBOL,
        dtype: str = "numeric",
        description: str = "",
        dependencies: list[str] | None = None,
        freshness_sla: timedelta | None = None,
        knowledge_lag: timedelta = timedelta(0),
        materialization: MaterializationMode | str = MaterializationMode.INCREMENTAL,
        owner: str = "",
        tags: list[str] | None = None,
    ) -> None:
        self.name = name
        self.group = group
        self.entity = Entity(entity) if isinstance(entity, str) else entity
        self.dtype = dtype
        self.description = description
        self.dependencies = dependencies or []
        self.freshness_sla = freshness_sla
        self.knowledge_lag = knowledge_lag
        self.materialization = MaterializationMode(materialization)
        self.transform = transform
        self.owner = owner
        self.tags = tags or []

        # Computed properties
        self.table_name = f"feature_{self.group}_{self.name}"
        self.definition_hash = _compute_definition_hash(
            name=self.name,
            transform=self.transform,
            dependencies=self.dependencies,
            dtype=self.dtype,
        )

    @property
    def freshness_sla_seconds(self) -> int | None:
        if self.freshness_sla is None:
            return None
        return int(self.freshness_sla.total_seconds())

    @property
    def knowledge_lag_seconds(self) -> int:
        return int(self.knowledge_lag.total_seconds())

    def to_registry_dict(self) -> dict[str, Any]:
        """Convert to a dict suitable for inserting into feature_registry."""
        return {
            "name": self.name,
            "group": self.group,
            "entity": self.entity.value,
            "dtype": self.dtype,
            "description": self.description,
            "dependencies": {"deps": self.dependencies},
            "transform_sql": self.transform,
            "definition_hash": self.definition_hash,
            "materialization": self.materialization.value,
            "freshness_sla_seconds": self.freshness_sla_seconds,
            "knowledge_lag_seconds": self.knowledge_lag_seconds,
            "owner": self.owner,
            "tags": {"tags": self.tags},
            "table_name": self.table_name,
        }

    def create_table_sql(self) -> str:
        """Generate the CREATE TABLE DDL for this feature's storage.

        All feature tables follow the canonical bitemporal shape.
        """
        return f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                symbol         TEXT        NOT NULL,
                event_ts       TIMESTAMPTZ NOT NULL,
                knowledge_ts   TIMESTAMPTZ NOT NULL,
                value          NUMERIC,
                value_version  SMALLINT    NOT NULL DEFAULT 1,
                source_hash    TEXT        NOT NULL,
                PRIMARY KEY (symbol, event_ts, knowledge_ts)
            );
            SELECT create_hypertable(
                '{self.table_name}', 'event_ts',
                chunk_time_interval => INTERVAL '90 days',
                if_not_exists => TRUE
            );
            CREATE INDEX IF NOT EXISTS ix_{self.table_name}_pit
                ON {self.table_name} (symbol, event_ts DESC, knowledge_ts DESC);
        """

    def pit_view_sql(self) -> str:
        """Generate the PIT-correct retrieval view for this feature."""
        return f"""
            CREATE OR REPLACE VIEW v_pit_{self.name} AS
            SELECT DISTINCT ON (symbol, event_ts)
                symbol,
                event_ts,
                knowledge_ts,
                value,
                value_version
            FROM {self.table_name}
            ORDER BY symbol, event_ts, knowledge_ts DESC, value_version DESC;
        """

    def __repr__(self) -> str:
        return (
            f"FeatureDefinition(name={self.name!r}, group={self.group!r}, "
            f"hash={self.definition_hash[:12]}...)"
        )
