"""Tests for ticker dictionary and entity resolution."""

from __future__ import annotations

import pytest
from astraeus_entities.aliases import extract_cashtags, normalize_company_name
from astraeus_entities.ticker_dict import TickerDictionary, TickerEntry, build_default_dictionary


@pytest.mark.unit
class TestTickerDictionary:
    """Tests for TickerDictionary lookups."""

    def test_add(self) -> None:
        d = TickerDictionary()
        entry = TickerEntry(
            symbol="TEST",
            company_name="Test Company",
            aliases=("Tester", "Testing"),
            sector="Technology"
        )
        d.add(entry)

        # Check by symbol
        assert "TEST" in d._by_symbol
        assert d._by_symbol["TEST"] == entry

        # Check by name
        assert "test company" in d._by_name
        assert d._by_name["test company"] == entry

        # Check by aliases
        assert "tester" in d._by_alias
        assert entry in d._by_alias["tester"]
        assert "testing" in d._by_alias
        assert entry in d._by_alias["testing"]

    def test_lookup_symbol_exact(self) -> None:
        d = build_default_dictionary()
        entry = d.lookup_symbol("AAPL")
        assert entry is not None
        assert entry.symbol == "AAPL"
        assert entry.company_name == "Apple Inc."

    def test_lookup_symbol_case_insensitive(self) -> None:
        d = build_default_dictionary()
        entry = d.lookup_symbol("aapl")
        assert entry is not None
        assert entry.symbol == "AAPL"

    def test_lookup_name(self) -> None:
        d = build_default_dictionary()
        entry = d.lookup_name("Apple Inc.")
        assert entry is not None
        assert entry.symbol == "AAPL"

    def test_lookup_alias(self) -> None:
        d = build_default_dictionary()
        entries = d.lookup_alias("iPhone-maker")
        assert len(entries) == 1
        assert entries[0].symbol == "AAPL"

    def test_resolve_symbol(self) -> None:
        d = build_default_dictionary()
        entries = d.resolve("MSFT")
        assert len(entries) == 1
        assert entries[0].symbol == "MSFT"

    def test_resolve_alias(self) -> None:
        d = build_default_dictionary()
        entries = d.resolve("Google")
        assert len(entries) == 1
        assert entries[0].symbol == "GOOGL"

    def test_ambiguous_symbol_detected(self) -> None:
        d = build_default_dictionary()
        assert d.is_ambiguous_symbol("T")
        assert d.is_ambiguous_symbol("V")
        assert not d.is_ambiguous_symbol("AAPL")

    def test_unknown_symbol_returns_none(self) -> None:
        d = build_default_dictionary()
        assert d.lookup_symbol("ZZZZ") is None

    def test_size(self) -> None:
        d = build_default_dictionary()
        assert d.size >= 10  # At least the defaults


@pytest.mark.unit
class TestAliases:
    """Tests for alias extraction and normalization."""

    def test_extract_cashtags(self) -> None:
        text = "I'm bullish on $AAPL and $MSFT today"
        matches = extract_cashtags(text)
        assert len(matches) == 2
        assert matches[0].normalized == "AAPL"
        assert matches[1].normalized == "MSFT"

    def test_extract_cashtag_with_dot(self) -> None:
        text = "Looking at $BRK.B for value"
        matches = extract_cashtags(text)
        assert len(matches) == 1
        assert matches[0].normalized == "BRK.B"

    def test_normalize_company_name(self) -> None:
        assert normalize_company_name("Apple Inc.") == "Apple"
        assert normalize_company_name("Microsoft Corporation") == "Microsoft"
        assert normalize_company_name("Tesla") == "Tesla"
        assert normalize_company_name("JPMorgan Chase & Co.") == "JPMorgan Chase &"
