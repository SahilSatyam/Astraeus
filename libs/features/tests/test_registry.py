"""Unit tests for the feature registry.

Tests registration, lookup, and update logic with mocked DB sessions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from astraeus_features.dsl import Entity, FeatureDefinition
from astraeus_features.registry import get_definition, list_features, register


@pytest.fixture
def sample_feature() -> FeatureDefinition:
    return FeatureDefinition(
        name="momentum_20d",
        group="price_derived",
        transform="SELECT symbol, event_ts, ln(close/lag(close, 20)) as value FROM ohlcv",
        entity=Entity.SYMBOL,
        dtype="numeric",
        description="20-day log momentum",
        dependencies=["ohlcv_daily"],
        owner="quant-research",
        tags=["factor", "momentum"],
    )


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


class TestRegister:
    """Test feature registration."""

    @pytest.mark.unit
    async def test_register_new_feature(self, mock_session, sample_feature):
        """Registering a new feature creates a registry entry."""
        # No existing feature
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result_mock

        row = await register(mock_session, sample_feature, create_table=False)

        # Should have called session.add with a new row
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.unit
    async def test_register_existing_same_hash_is_noop(self, mock_session, sample_feature):
        """Re-registering with same hash is a no-op."""
        existing = MagicMock()
        existing.definition_hash = sample_feature.definition_hash

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = result_mock

        row = await register(mock_session, sample_feature, create_table=False)

        assert row == existing
        mock_session.add.assert_not_called()

    @pytest.mark.unit
    async def test_register_existing_different_hash_updates(self, mock_session, sample_feature):
        """Re-registering with different hash updates the entry."""
        existing = MagicMock()
        existing.definition_hash = "old-hash-different"

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = result_mock

        row = await register(mock_session, sample_feature, create_table=False)

        # Should update the existing row's hash
        assert existing.definition_hash == sample_feature.definition_hash
        mock_session.flush.assert_called_once()


class TestGetDefinition:
    """Test feature lookup."""

    @pytest.mark.unit
    async def test_get_existing_feature(self, mock_session):
        """Looking up an existing feature returns it."""
        expected = MagicMock()
        expected.name = "momentum_20d"

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = expected
        mock_session.execute.return_value = result_mock

        result = await get_definition(mock_session, "momentum_20d")
        assert result == expected

    @pytest.mark.unit
    async def test_get_nonexistent_feature(self, mock_session):
        """Looking up a non-existent feature returns None."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result_mock

        result = await get_definition(mock_session, "nonexistent")
        assert result is None


class TestListFeatures:
    """Test feature listing."""

    @pytest.mark.unit
    async def test_list_all_features(self, mock_session):
        """List features returns all registered features."""
        features = [MagicMock(name="f1"), MagicMock(name="f2")]

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = features
        mock_session.execute.return_value = result_mock

        result = await list_features(mock_session)
        assert len(result) == 2
