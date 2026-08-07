"""Tests for alias extraction."""

from __future__ import annotations

import pytest
from astraeus_entities.aliases import extract_cashtags, AliasMatch


@pytest.mark.unit
class TestExtractCashtags:
    """Tests for extracting cashtags from text."""

    def test_single_cashtag(self) -> None:
        text = "Buy some $AAPL today."
        matches = extract_cashtags(text)
        assert len(matches) == 1
        assert matches[0].normalized == "AAPL"
        assert matches[0].match_type == "cashtag"

    def test_multiple_cashtags(self) -> None:
        text = "$MSFT and $GOOGL are performing well."
        matches = extract_cashtags(text)
        assert len(matches) == 2
        assert matches[0].normalized == "MSFT"
        assert matches[1].normalized == "GOOGL"

    def test_cashtag_at_end(self) -> None:
        text = "I like $TSLA"
        matches = extract_cashtags(text)
        assert len(matches) == 1
        assert matches[0].normalized == "TSLA"

    def test_cashtags_with_punctuation(self) -> None:
        text = "Watch $NVDA, $AMD, and $INTC!"
        matches = extract_cashtags(text)
        assert len(matches) == 3

        assert matches[0].normalized == "NVDA"
        assert matches[1].normalized == "AMD"
        assert matches[2].normalized == "INTC"

    def test_cashtag_with_class_letters(self) -> None:
        text = "Investing in $BRK.B and $BRK.A."
        matches = extract_cashtags(text)
        assert len(matches) == 2

        assert matches[0].normalized == "BRK.B"
        assert matches[1].normalized == "BRK.A"

    def test_lowercase_and_invalid_cashtags_ignored(self) -> None:
        text = "This is $aapl, $123, and just a $ sign."
        matches = extract_cashtags(text)
        assert len(matches) == 0

    def test_messy_cashtags(self) -> None:
        text = "Here is a valid one: $AAPL. And an invalid one $APPLEINC"
        matches = extract_cashtags(text)
        assert len(matches) == 1
        assert matches[0].normalized == "AAPL"
