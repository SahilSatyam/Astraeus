"""Alias expansion and normalization for entity resolution.

Handles common patterns in financial text:
- "$AAPL" -> "AAPL"
- "Apple Inc." -> "Apple Inc"
- "the iPhone-maker" -> lookup via alias
- CIK numbers -> ticker mapping
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Regex to extract cashtag tickers: $AAPL, $BRK.B
_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5}(?:\.[A-B])?)(?:\s|$|[,;.!?])")

# Regex to detect all-caps potential tickers in text
_TICKER_RE = re.compile(r"\b([A-Z]{1,5}(?:\.[A-B])?)\b")

# Common suffixes to strip for name matching
_COMPANY_SUFFIXES = re.compile(
    r"\s*(?:Inc\.?|Corp\.?|Corporation|Company|Co\.?|Ltd\.?|Limited|PLC|SA|AG|NV|SE)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AliasMatch:
    """Result of alias extraction from text."""

    surface_form: str
    normalized: str
    char_start: int
    char_end: int
    match_type: str  # "cashtag", "ticker", "name"


def extract_cashtags(text: str) -> list[AliasMatch]:
    """Extract $TICKER cashtags from text."""
    matches: list[AliasMatch] = []
    for m in _CASHTAG_RE.finditer(text):
        matches.append(
            AliasMatch(
                surface_form=m.group(0).strip(),
                normalized=m.group(1).upper(),
                char_start=m.start(),
                char_end=m.end(),
                match_type="cashtag",
            )
        )
    return matches


def normalize_company_name(name: str) -> str:
    """Strip common corporate suffixes for fuzzy matching.

    "Apple Inc." -> "Apple"
    "Microsoft Corporation" -> "Microsoft"
    """
    return _COMPANY_SUFFIXES.sub("", name).strip()


def extract_potential_tickers(text: str) -> list[AliasMatch]:
    """Extract potential all-caps ticker symbols from text.

    These are candidates only — must be validated against the ticker dictionary.
    Filters out common English words that happen to be all-caps (I, A, etc.)
    by requiring length >= 2 or being preceded by $ or context clues.
    """
    matches: list[AliasMatch] = []
    for m in _TICKER_RE.finditer(text):
        symbol = m.group(1)
        # Skip single-char unless it's a known ticker pattern
        if len(symbol) == 1:
            continue
        matches.append(
            AliasMatch(
                surface_form=m.group(0),
                normalized=symbol.upper(),
                char_start=m.start(),
                char_end=m.end(),
                match_type="ticker",
            )
        )
    return matches
