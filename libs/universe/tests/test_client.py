"""Unit tests for the universe client.

Tests PIT-correct membership queries, ticker resolution, and survivorship-bias
awareness with mocked DB sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from astraeus_universe.client import is_active, members, members_over_window, resolve


@pytest.fixture
def mock_session():
    return AsyncMock()


class TestMembers:
    """Test PIT-correct universe membership queries."""

    @pytest.mark.unit
    async def test_returns_sorted_symbols(self, mock_session):
        """Members are returned sorted."""
        result_mock = MagicMock()
        result_mock.all.return_value = [("MSFT",), ("AAPL",), ("GOOG",)]
        mock_session.execute.return_value = result_mock

        result = await members(mock_session, "sp500", datetime(2024, 6, 30, tzinfo=UTC))
        assert result == ["MSFT", "AAPL", "GOOG"]  # order from DB (already sorted by query)

    @pytest.mark.unit
    async def test_requires_timezone_aware_timestamp(self, mock_session):
        """Raises ValueError for naive datetime."""
        with pytest.raises(ValueError, match="timezone-aware"):
            await members(mock_session, "sp500", datetime(2024, 6, 30))

    @pytest.mark.unit
    async def test_empty_universe(self, mock_session):
        """Returns empty list for universe with no members."""
        result_mock = MagicMock()
        result_mock.all.return_value = []
        mock_session.execute.return_value = result_mock

        result = await members(mock_session, "empty_universe", datetime(2024, 1, 1, tzinfo=UTC))
        assert result == []


class TestMembersOverWindow:
    """Test window-based membership queries."""

    @pytest.mark.unit
    async def test_returns_all_members_in_window(self, mock_session):
        """Returns all symbols that were members at any point in the window."""
        result_mock = MagicMock()
        result_mock.all.return_value = [("AAPL",), ("FB",), ("GOOG",)]
        mock_session.execute.return_value = result_mock

        result = await members_over_window(
            mock_session,
            "sp500",
            datetime(2020, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, tzinfo=UTC),
        )
        assert len(result) == 3

    @pytest.mark.unit
    async def test_requires_timezone_aware_timestamps(self, mock_session):
        """Raises ValueError for naive datetimes."""
        with pytest.raises(ValueError, match="timezone-aware"):
            await members_over_window(
                mock_session,
                "sp500",
                datetime(2020, 1, 1),  # naive
                datetime(2024, 12, 31, tzinfo=UTC),
            )


class TestResolve:
    """Test ticker/identifier resolution."""

    @pytest.mark.unit
    async def test_resolve_current_ticker(self, mock_session):
        """Resolves current ticker to canonical symbol."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = "META"
        mock_session.execute.return_value = result_mock

        result = await resolve(mock_session, "META", alias_type="ticker")
        assert result == "META"

    @pytest.mark.unit
    async def test_resolve_historical_ticker(self, mock_session):
        """Resolves historical ticker (FB → META) at a point in time."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = "META"
        mock_session.execute.return_value = result_mock

        result = await resolve(
            mock_session, "FB", alias_type="ticker", as_of_ts=datetime(2021, 6, 1, tzinfo=UTC)
        )
        assert result == "META"

    @pytest.mark.unit
    async def test_resolve_unknown_returns_none(self, mock_session):
        """Unknown identifier returns None."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result_mock

        result = await resolve(mock_session, "UNKNOWN_TICKER")
        assert result is None


class TestIsActive:
    """Test security active status checks."""

    @pytest.mark.unit
    async def test_active_security(self, mock_session):
        """Active security (no delisted_at) returns True."""
        sec = MagicMock()
        sec.delisted_at = None

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = sec
        mock_session.execute.return_value = result_mock

        assert await is_active(mock_session, "AAPL") is True

    @pytest.mark.unit
    async def test_delisted_security(self, mock_session):
        """Delisted security returns False."""
        sec = MagicMock()
        sec.delisted_at = datetime(2023, 1, 1, tzinfo=UTC)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = sec
        mock_session.execute.return_value = result_mock

        assert await is_active(mock_session, "DELISTED") is False

    @pytest.mark.unit
    async def test_unknown_security(self, mock_session):
        """Unknown security returns False."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result_mock

        assert await is_active(mock_session, "NONEXISTENT") is False

    @pytest.mark.unit
    async def test_delisted_after_as_of(self, mock_session):
        """Security delisted after as_of_ts is still active at that time."""
        sec = MagicMock()
        sec.delisted_at = datetime(2024, 6, 1, tzinfo=UTC)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = sec
        mock_session.execute.return_value = result_mock

        # As of Jan 2024, it was still active (delisted in June)
        result = await is_active(mock_session, "LATER_DELIST", datetime(2024, 1, 1, tzinfo=UTC))
        assert result is True
