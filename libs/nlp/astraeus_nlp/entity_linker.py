"""Entity linker — resolves NER spans to canonical ticker symbols.

The linking pipeline:
1. NER proposes candidate spans (ORG entities)
2. Dictionary confirms: exact symbol match, name match, or alias match
3. Context reranker handles ambiguous cases (e.g., "Apple" — fruit or AAPL?)

Confidence threshold: mentions below 0.7 are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from astraeus_entities.aliases import extract_cashtags, normalize_company_name
from astraeus_entities.ticker_dict import TickerDictionary, TickerEntry

from astraeus_nlp.ner import NERSpan

logger = structlog.get_logger("astraeus.nlp.entity_linker")

# Minimum confidence to keep a linked entity
DEFAULT_CONFIDENCE_THRESHOLD = 0.7

# Context window (chars) around a mention for disambiguation
_CONTEXT_WINDOW = 200

# Financial context keywords that boost confidence for ambiguous tickers
_FINANCE_CONTEXT_WORDS = frozenset(
    {
        "stock",
        "share",
        "shares",
        "price",
        "market",
        "trading",
        "investor",
        "earnings",
        "revenue",
        "profit",
        "loss",
        "dividend",
        "quarter",
        "annual",
        "CEO",
        "CFO",
        "IPO",
        "SEC",
        "filing",
        "analyst",
        "upgrade",
        "downgrade",
        "buy",
        "sell",
        "hold",
        "target",
        "valuation",
        "PE",
        "EPS",
        "guidance",
        "bull",
        "bear",
        "rally",
        "crash",
        "volatility",
        "options",
        "calls",
        "puts",
        "transaction",
        "volume",
        "growth",
        "reported",
        "subscriber",
        "payment",
        "payments",
    }
)


@dataclass(frozen=True, slots=True)
class LinkedEntity:
    """A resolved entity mention with canonical ticker."""

    surface_form: str
    canonical_id: str  # ticker symbol
    entity_kind: str  # "ticker", "org", "person"
    confidence: float
    char_start: int
    char_end: int
    match_method: str  # "cashtag", "symbol", "name", "alias", "ner+dict"


class EntityLinker:
    """Links NER spans and text patterns to canonical ticker symbols.

    Combines multiple signals:
    - Cashtag extraction ($AAPL)
    - Direct symbol matching
    - Company name matching via dictionary
    - NER ORG entities cross-referenced with dictionary
    - Context-based disambiguation for ambiguous symbols
    """

    def __init__(
        self,
        dictionary: TickerDictionary,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._dict = dictionary
        self._threshold = confidence_threshold

    def link(self, text: str, ner_spans: list[NERSpan]) -> list[LinkedEntity]:
        """Link entities in text to canonical tickers.

        Combines cashtag extraction with NER-based linking.
        Deduplicates overlapping mentions, keeping highest confidence.
        """
        entities: list[LinkedEntity] = []

        # 1. Extract cashtags (highest confidence — explicit ticker mention)
        for cashtag in extract_cashtags(text):
            entry = self._dict.lookup_symbol(cashtag.normalized)
            if entry:
                entities.append(
                    LinkedEntity(
                        surface_form=cashtag.surface_form,
                        canonical_id=entry.symbol,
                        entity_kind="ticker",
                        confidence=0.99,
                        char_start=cashtag.char_start,
                        char_end=cashtag.char_end,
                        match_method="cashtag",
                    )
                )

        # 2. Process NER ORG spans against dictionary
        for span in ner_spans:
            if span.label != "ORG":
                continue

            linked = self._resolve_org_span(span, text)
            if linked:
                entities.append(linked)

        # 3. Deduplicate overlapping mentions
        entities = self._deduplicate(entities)

        # 4. Filter by confidence threshold
        entities = [e for e in entities if e.confidence >= self._threshold]

        return entities

    def _resolve_org_span(self, span: NERSpan, full_text: str) -> LinkedEntity | None:
        """Resolve an ORG NER span to a ticker using the dictionary."""
        surface = span.text.strip()

        # Try exact symbol match
        entry = self._dict.lookup_symbol(surface)
        if entry and not entry.is_ambiguous:
            return LinkedEntity(
                surface_form=surface,
                canonical_id=entry.symbol,
                entity_kind="ticker",
                confidence=0.95,
                char_start=span.start_char,
                char_end=span.end_char,
                match_method="symbol",
            )

        # Try company name match
        entry = self._dict.lookup_name(surface)
        if entry:
            return LinkedEntity(
                surface_form=surface,
                canonical_id=entry.symbol,
                entity_kind="ticker",
                confidence=0.92,
                char_start=span.start_char,
                char_end=span.end_char,
                match_method="name",
            )

        # Try normalized name match
        normalized = normalize_company_name(surface)
        entry = self._dict.lookup_name(normalized)
        if entry:
            return LinkedEntity(
                surface_form=surface,
                canonical_id=entry.symbol,
                entity_kind="ticker",
                confidence=0.88,
                char_start=span.start_char,
                char_end=span.end_char,
                match_method="name",
            )

        # Try alias match
        candidates = self._dict.lookup_alias(surface)
        if not candidates:
            candidates = self._dict.lookup_alias(normalized)

        if len(candidates) == 1:
            entry = candidates[0]
            confidence = 0.85
            if entry.is_ambiguous:
                confidence = self._disambiguate_with_context(
                    surface, full_text, span.start_char, span.end_char
                )
            return LinkedEntity(
                surface_form=surface,
                canonical_id=entry.symbol,
                entity_kind="ticker",
                confidence=confidence,
                char_start=span.start_char,
                char_end=span.end_char,
                match_method="alias",
            )

        if len(candidates) > 1:
            # Multiple candidates — use context to disambiguate
            best = self._pick_best_candidate(candidates, surface, full_text, span.start_char)
            if best:
                return LinkedEntity(
                    surface_form=surface,
                    canonical_id=best.symbol,
                    entity_kind="ticker",
                    confidence=0.72,
                    char_start=span.start_char,
                    char_end=span.end_char,
                    match_method="ner+dict",
                )

        return None

    def _disambiguate_with_context(self, surface: str, text: str, start: int, end: int) -> float:
        """Use surrounding context to determine if an ambiguous mention is financial.

        Looks for financial keywords in the context window. More keywords = higher confidence.
        """
        ctx_start = max(0, start - _CONTEXT_WINDOW)
        ctx_end = min(len(text), end + _CONTEXT_WINDOW)
        context = text[ctx_start:ctx_end].lower()

        # Count financial context words
        finance_hits = sum(1 for word in _FINANCE_CONTEXT_WORDS if word in context)

        # Scale confidence: 0 hits = 0.4, 1 hit = 0.6, 2+ hits = 0.8+
        if finance_hits == 0:
            return 0.4
        if finance_hits == 1:
            return 0.65
        if finance_hits == 2:
            return 0.80
        return min(0.92, 0.80 + finance_hits * 0.03)

    def _pick_best_candidate(
        self,
        candidates: list[TickerEntry],
        surface: str,
        text: str,
        start: int,
    ) -> TickerEntry | None:
        """Pick the best candidate from multiple matches using context."""
        # Simple heuristic: prefer non-ambiguous, then by sector context
        non_ambiguous = [c for c in candidates if not c.is_ambiguous]
        if len(non_ambiguous) == 1:
            return non_ambiguous[0]

        # Fall back to first candidate (could be improved with a trained reranker)
        return candidates[0] if candidates else None

    def _deduplicate(self, entities: list[LinkedEntity]) -> list[LinkedEntity]:
        """Remove overlapping mentions, keeping highest confidence."""
        if not entities:
            return []

        # Sort by start position, then by confidence descending
        sorted_entities = sorted(entities, key=lambda e: (e.char_start, -e.confidence))

        result: list[LinkedEntity] = []
        last_end = -1

        for entity in sorted_entities:
            if entity.char_start >= last_end:
                result.append(entity)
                last_end = entity.char_end

        return result
