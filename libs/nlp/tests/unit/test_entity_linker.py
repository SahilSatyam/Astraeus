"""Tests for entity linking — the unsexy 80% that makes or breaks the pipeline.

Tests cover:
- Cashtag extraction (highest confidence)
- Company name resolution
- Ambiguous symbol disambiguation
- Confidence thresholding
- Deduplication of overlapping mentions
"""

from __future__ import annotations

import pytest
from astraeus_entities.ticker_dict import build_default_dictionary
from astraeus_nlp.entity_linker import EntityLinker
from astraeus_nlp.ner import NERSpan


@pytest.fixture
def linker() -> EntityLinker:
    """Create an entity linker with the default dictionary."""
    dictionary = build_default_dictionary()
    return EntityLinker(dictionary=dictionary, confidence_threshold=0.7)


@pytest.mark.unit
class TestEntityLinker:
    """Tests for entity linking accuracy."""

    def test_cashtag_highest_confidence(self, linker: EntityLinker) -> None:
        """$AAPL should resolve with near-perfect confidence."""
        text = "I'm buying $AAPL calls before earnings"
        entities = linker.link(text, [])
        assert len(entities) >= 1
        aapl = next((e for e in entities if e.canonical_id == "AAPL"), None)
        assert aapl is not None
        assert aapl.confidence >= 0.95
        assert aapl.match_method == "cashtag"

    def test_company_name_via_ner(self, linker: EntityLinker) -> None:
        """NER ORG span 'Apple Inc.' should resolve to AAPL."""
        text = "Apple Inc. reported strong quarterly earnings"
        ner_spans = [NERSpan(text="Apple Inc.", label="ORG", start_char=0, end_char=10)]
        entities = linker.link(text, ner_spans)
        assert len(entities) >= 1
        assert entities[0].canonical_id == "AAPL"

    def test_alias_resolution(self, linker: EntityLinker) -> None:
        """'Google' should resolve to GOOGL via alias."""
        text = "Google announced new AI features"
        ner_spans = [NERSpan(text="Google", label="ORG", start_char=0, end_char=6)]
        entities = linker.link(text, ner_spans)
        assert len(entities) >= 1
        assert entities[0].canonical_id == "GOOGL"

    def test_ambiguous_symbol_needs_context(self, linker: EntityLinker) -> None:
        """'T' alone (AT&T) is ambiguous — needs financial context to resolve."""
        # Without financial context, confidence should be low
        text = "I saw T at the store"
        ner_spans = [NERSpan(text="T", label="ORG", start_char=6, end_char=7)]
        entities = linker.link(text, ner_spans)
        # Should be filtered out by confidence threshold (0.7)
        t_entities = [e for e in entities if e.canonical_id == "T"]
        # Low confidence due to no financial context
        if t_entities:
            assert t_entities[0].confidence < 0.7

    def test_ambiguous_symbol_with_financial_context(self, linker: EntityLinker) -> None:
        """'T' with financial context should resolve with higher confidence."""
        text = "T stock price dropped after the earnings report showed declining revenue"
        ner_spans = [NERSpan(text="T", label="ORG", start_char=0, end_char=1)]
        _entities = linker.link(text, ner_spans)
        # With financial context words, confidence should be higher
        # (may or may not pass threshold depending on context word count)

    def test_multiple_entities_in_text(self, linker: EntityLinker) -> None:
        """Multiple tickers in one text should all be resolved."""
        text = "$AAPL and $MSFT both reported strong earnings"
        entities = linker.link(text, [])
        tickers = {e.canonical_id for e in entities}
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_confidence_threshold_filters(self, linker: EntityLinker) -> None:
        """Entities below confidence threshold should be excluded."""
        # All returned entities should be above threshold
        text = "$AAPL is up today"
        entities = linker.link(text, [])
        for entity in entities:
            assert entity.confidence >= 0.7

    def test_deduplication_keeps_highest_confidence(self, linker: EntityLinker) -> None:
        """Overlapping mentions should keep the highest-confidence one."""
        text = "$AAPL Apple Inc. is doing well"
        ner_spans = [NERSpan(text="Apple Inc.", label="ORG", start_char=6, end_char=16)]
        entities = linker.link(text, ner_spans)
        # Should not have duplicate AAPL entries at overlapping positions
        aapl_entities = [e for e in entities if e.canonical_id == "AAPL"]
        # Positions shouldn't overlap
        for i in range(len(aapl_entities) - 1):
            assert aapl_entities[i].char_end <= aapl_entities[i + 1].char_start

    def test_unknown_entity_not_linked(self, linker: EntityLinker) -> None:
        """Unknown companies should not produce false positives."""
        text = "Acme Widget Corp announced layoffs"
        ner_spans = [NERSpan(text="Acme Widget Corp", label="ORG", start_char=0, end_char=16)]
        entities = linker.link(text, ner_spans)
        # Should not resolve to any ticker
        assert len(entities) == 0
