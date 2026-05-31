"""Unit tests for the feature definition DSL.

Tests definition hashing, table name generation, PIT view SQL,
and validation of feature definitions.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from astraeus_features.dsl import (
    Entity,
    FeatureDefinition,
    MaterializationMode,
    _canonicalize_sql,
    sql_transform,
)


class TestFeatureDefinition:
    """Test FeatureDefinition construction and properties."""

    @pytest.mark.unit
    def test_basic_construction(self):
        fd = FeatureDefinition(
            name="momentum_20d",
            group="price_derived",
            transform=sql_transform("SELECT symbol, event_ts FROM ohlcv"),
            entity=Entity.SYMBOL,
            dtype="numeric",
        )
        assert fd.name == "momentum_20d"
        assert fd.group == "price_derived"
        assert fd.entity == Entity.SYMBOL
        assert fd.dtype == "numeric"

    @pytest.mark.unit
    def test_table_name_generation(self):
        fd = FeatureDefinition(
            name="rsi_14",
            group="technical",
            transform="SELECT 1",
        )
        assert fd.table_name == "feature_technical_rsi_14"

    @pytest.mark.unit
    def test_definition_hash_deterministic(self):
        """Same definition produces same hash."""
        fd1 = FeatureDefinition(
            name="vol_20d",
            group="risk",
            transform="SELECT symbol, stddev(ret) FROM returns GROUP BY symbol",
            dependencies=["ohlcv_daily"],
            dtype="numeric",
        )
        fd2 = FeatureDefinition(
            name="vol_20d",
            group="risk",
            transform="SELECT symbol, stddev(ret) FROM returns GROUP BY symbol",
            dependencies=["ohlcv_daily"],
            dtype="numeric",
        )
        assert fd1.definition_hash == fd2.definition_hash

    @pytest.mark.unit
    def test_definition_hash_changes_with_transform(self):
        """Different transform produces different hash."""
        fd1 = FeatureDefinition(
            name="vol_20d",
            group="risk",
            transform="SELECT stddev(ret) FROM returns",
        )
        fd2 = FeatureDefinition(
            name="vol_20d",
            group="risk",
            transform="SELECT variance(ret) FROM returns",
        )
        assert fd1.definition_hash != fd2.definition_hash

    @pytest.mark.unit
    def test_definition_hash_changes_with_dependencies(self):
        """Different dependencies produce different hash."""
        fd1 = FeatureDefinition(
            name="momentum_20d",
            group="price",
            transform="SELECT 1",
            dependencies=["ohlcv_daily"],
        )
        fd2 = FeatureDefinition(
            name="momentum_20d",
            group="price",
            transform="SELECT 1",
            dependencies=["ohlcv_daily", "splits"],
        )
        assert fd1.definition_hash != fd2.definition_hash

    @pytest.mark.unit
    def test_definition_hash_ignores_whitespace(self):
        """Reformatting SQL doesn't change the hash."""
        fd1 = FeatureDefinition(
            name="test",
            group="test",
            transform="SELECT symbol, event_ts FROM ohlcv WHERE symbol = :sym",
        )
        fd2 = FeatureDefinition(
            name="test",
            group="test",
            transform="SELECT   symbol,\n  event_ts\nFROM   ohlcv\nWHERE symbol = :sym",
        )
        assert fd1.definition_hash == fd2.definition_hash

    @pytest.mark.unit
    def test_freshness_sla_seconds(self):
        fd = FeatureDefinition(
            name="test",
            group="test",
            transform="SELECT 1",
            freshness_sla=timedelta(hours=2),
        )
        assert fd.freshness_sla_seconds == 7200

    @pytest.mark.unit
    def test_freshness_sla_none(self):
        fd = FeatureDefinition(
            name="test",
            group="test",
            transform="SELECT 1",
        )
        assert fd.freshness_sla_seconds is None

    @pytest.mark.unit
    def test_knowledge_lag_seconds(self):
        fd = FeatureDefinition(
            name="test",
            group="test",
            transform="SELECT 1",
            knowledge_lag=timedelta(minutes=30),
        )
        assert fd.knowledge_lag_seconds == 1800

    @pytest.mark.unit
    def test_to_registry_dict(self):
        fd = FeatureDefinition(
            name="momentum_20d",
            group="price_derived",
            transform="SELECT 1",
            entity=Entity.SYMBOL,
            dtype="numeric",
            description="20-day momentum",
            dependencies=["ohlcv_daily"],
            owner="quant-research",
            tags=["factor", "momentum"],
        )
        d = fd.to_registry_dict()
        assert d["name"] == "momentum_20d"
        assert d["group"] == "price_derived"
        assert d["entity"] == "symbol"
        assert d["dependencies"] == {"deps": ["ohlcv_daily"]}
        assert d["tags"] == {"tags": ["factor", "momentum"]}
        assert d["table_name"] == "feature_price_derived_momentum_20d"

    @pytest.mark.unit
    def test_create_table_sql_contains_hypertable(self):
        fd = FeatureDefinition(
            name="rsi_14",
            group="technical",
            transform="SELECT 1",
        )
        sql = fd.create_table_sql()
        assert "CREATE TABLE IF NOT EXISTS feature_technical_rsi_14" in sql
        assert "create_hypertable" in sql
        assert "event_ts" in sql
        assert "knowledge_ts" in sql

    @pytest.mark.unit
    def test_pit_view_sql(self):
        fd = FeatureDefinition(
            name="vol_20d",
            group="risk",
            transform="SELECT 1",
        )
        sql = fd.pit_view_sql()
        assert "v_pit_vol_20d" in sql
        assert "DISTINCT ON" in sql
        assert "knowledge_ts DESC" in sql

    @pytest.mark.unit
    def test_materialization_modes(self):
        for mode in MaterializationMode:
            fd = FeatureDefinition(
                name="test",
                group="test",
                transform="SELECT 1",
                materialization=mode,
            )
            assert fd.materialization == mode

    @pytest.mark.unit
    def test_repr(self):
        fd = FeatureDefinition(
            name="momentum_20d",
            group="price_derived",
            transform="SELECT 1",
        )
        r = repr(fd)
        assert "momentum_20d" in r
        assert "price_derived" in r


class TestCanonicalizeSql:
    """Test SQL canonicalization for deterministic hashing."""

    @pytest.mark.unit
    def test_strips_comments(self):
        sql = "SELECT 1 -- this is a comment\nFROM foo"
        result = _canonicalize_sql(sql)
        assert "comment" not in result

    @pytest.mark.unit
    def test_strips_block_comments(self):
        sql = "SELECT /* block */ 1 FROM foo"
        result = _canonicalize_sql(sql)
        assert "block" not in result

    @pytest.mark.unit
    def test_collapses_whitespace(self):
        sql = "SELECT   1\n\n  FROM   foo"
        result = _canonicalize_sql(sql)
        assert "  " not in result

    @pytest.mark.unit
    def test_lowercases(self):
        sql = "SELECT Symbol FROM OHLCV"
        result = _canonicalize_sql(sql)
        assert result == "select symbol from ohlcv"


class TestSqlTransform:
    """Test the sql_transform helper."""

    @pytest.mark.unit
    def test_dedents_and_strips(self):
        result = sql_transform("""
            SELECT symbol, event_ts
            FROM ohlcv_daily
            WHERE symbol = :sym
        """)
        assert result.startswith("SELECT")
        assert result.endswith(":sym")
