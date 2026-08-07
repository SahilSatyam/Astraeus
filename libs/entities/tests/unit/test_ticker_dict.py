"""Tests for ticker dictionary and entity resolution."""

from __future__ import annotations

import pytest
from astraeus_entities.aliases import extract_cashtags, normalize_company_name
from astraeus_entities.ticker_dict import build_default_dictionary


@pytest.mark.unit
class TestTickerDictionary:
    """Tests for TickerDictionary lookups."""

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

    @pytest.mark.parametrize(
        ("dirty_name", "expected_clean"),
        [
            # Standard suffixes
            ("Apple Inc.", "Apple"),
            ("Microsoft Corporation", "Microsoft"),
            ("Tesla", "Tesla"),
            ("JPMorgan Chase & Co.", "JPMorgan Chase &"),
            ("Sony Corp", "Sony"),
            ("Sony Corp.", "Sony"),
            ("Acme Co", "Acme"),
            ("Acme Co.", "Acme"),
            # International suffixes
            ("Bayer AG", "Bayer"),
            ("Shell PLC", "Shell"),
            ("Airbus SE", "Airbus"),
            ("Spotify NV", "Spotify"),
            ("Danone SA", "Danone"),
            # Case variations
            ("apple inc", "apple"),
            ("MICROSOFT CORPORATION", "MICROSOFT"),
            ("Tesla LTD", "Tesla"),
            ("Alphabet LIMITED", "Alphabet"),
            # Edge cases (spacing)
            ("Apple  Inc.", "Apple"),
            ("Apple Inc.  ", "Apple"),
            # Suffix-like words inside the name should not be stripped
            ("Company Inc.", "Company"),
            ("The Corp Limited", "The Corp"),
            ("Incognito Systems", "Incognito Systems"),
            ("Agilent Technologies", "Agilent Technologies"),
        ],
    )
    def test_normalize_company_name(self, dirty_name: str, expected_clean: str) -> None:
        assert normalize_company_name(dirty_name) == expected_clean
