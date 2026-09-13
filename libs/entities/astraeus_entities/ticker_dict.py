"""Ticker dictionary — maps company names and aliases to canonical tickers.

The dictionary is the first-pass filter for entity linking. NER proposes
candidate spans, the dictionary confirms or rejects them. Ambiguous cases
(e.g., "Apple" could be fruit or AAPL) are flagged for the reranker.

The dictionary is loaded once at startup and held in memory. It's small
enough (~10K entries for US equities) that this is fine.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TickerEntry:
    """A single ticker with its canonical name and known aliases."""

    symbol: str
    company_name: str
    aliases: tuple[str, ...] = ()
    sector: str | None = None
    is_ambiguous: bool = False  # e.g., "T" (AT&T vs the letter)


class TickerDictionary:
    """In-memory ticker dictionary for entity resolution.

    Supports:
    - Exact symbol lookup: "AAPL" -> TickerEntry
    - Name/alias lookup: "Apple Inc" -> TickerEntry
    - Fuzzy prefix matching for partial names
    - Ambiguity detection for common-word tickers
    """

    # Tickers that are common English words — always ambiguous
    _AMBIGUOUS_SYMBOLS: frozenset[str] = frozenset(
        {
            "A",
            "B",
            "C",
            "D",
            "F",
            "G",
            "K",
            "L",
            "M",
            "N",
            "O",
            "R",
            "T",
            "U",
            "V",
            "W",
            "X",
            "Y",
            "ALL",
            "ARE",
            "BIG",
            "CAN",
            "CAR",
            "CAT",
            "DAY",
            "DO",
            "IT",
            "MAN",
            "NOW",
            "ON",
            "OR",
            "OUT",
            "RUN",
            "SEE",
            "SO",
            "SUN",
            "TEN",
            "TWO",
            "WAR",
            "WAS",
            "BEST",
            "BILL",
            "COST",
            "FAST",
            "FIVE",
            "GOOD",
            "HEAR",
            "HOPE",
            "LIFE",
            "LOVE",
            "OPEN",
            "PLAY",
            "REAL",
            "RIDE",
            "ROCK",
            "SAFE",
            "TRUE",
            "WELL",
        }
    )

    def __init__(self) -> None:
        self._by_symbol: dict[str, TickerEntry] = {}
        self._by_name: dict[str, TickerEntry] = {}  # lowercased name -> entry
        self._by_alias: dict[str, list[TickerEntry]] = {}  # lowercased alias -> entries

    def add(self, entry: TickerEntry) -> None:
        """Add a ticker entry to the dictionary."""
        self._by_symbol[entry.symbol.upper()] = entry
        self._by_name[entry.company_name.lower()] = entry
        for alias in entry.aliases:
            key = alias.lower()
            self._by_alias.setdefault(key, []).append(entry)

    def lookup_symbol(self, symbol: str) -> TickerEntry | None:
        """Exact symbol lookup."""
        return self._by_symbol.get(symbol.upper())

    def lookup_name(self, name: str) -> TickerEntry | None:
        """Exact company name lookup (case-insensitive)."""
        return self._by_name.get(name.lower())

    def lookup_alias(self, alias: str) -> list[TickerEntry]:
        """Alias lookup — may return multiple entries for ambiguous aliases."""
        return self._by_alias.get(alias.lower(), [])

    def resolve(self, surface_form: str) -> list[TickerEntry]:
        """Attempt to resolve a surface form to ticker entries.

        Tries in order: exact symbol, exact name, alias lookup.
        Returns all candidates (may be empty or multiple for ambiguous forms).
        """
        # Try exact symbol
        upper = surface_form.upper()
        if upper in self._by_symbol:
            return [self._by_symbol[upper]]

        # Try exact name
        lower = surface_form.lower()
        if lower in self._by_name:
            return [self._by_name[lower]]

        # Try alias
        return self._by_alias.get(lower, [])

    def is_ambiguous_symbol(self, symbol: str) -> bool:
        """Check if a symbol is a common English word (needs context disambiguation)."""
        return symbol.upper() in self._AMBIGUOUS_SYMBOLS

    @property
    def size(self) -> int:
        return len(self._by_symbol)

    def symbols(self) -> Iterator[str]:
        """Iterate over all known symbols."""
        yield from self._by_symbol.keys()

    @classmethod
    def from_csv(cls, path: Path) -> TickerDictionary:
        """Load dictionary from a CSV file.

        Expected columns: symbol, company_name, aliases (pipe-separated), sector
        """
        dictionary = cls()
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row["symbol"].strip().upper()
                aliases_raw = row.get("aliases", "")
                aliases = tuple(a.strip() for a in aliases_raw.split("|") if a.strip())
                entry = TickerEntry(
                    symbol=symbol,
                    company_name=row["company_name"].strip(),
                    aliases=aliases,
                    sector=row.get("sector", "").strip() or None,
                    is_ambiguous=symbol in cls._AMBIGUOUS_SYMBOLS,
                )
                dictionary.add(entry)
        return dictionary

    @classmethod
    def from_instruments_db(cls, rows: list[dict[str, str | None]]) -> TickerDictionary:
        """Build dictionary from the instruments table rows.

        Each row should have: symbol, company_name (optional), sector (optional).
        """
        dictionary = cls()
        for row in rows:
            symbol = (row.get("symbol") or "").upper()
            if not symbol:
                continue
            company_name = row.get("company_name") or symbol
            entry = TickerEntry(
                symbol=symbol,
                company_name=company_name,
                sector=row.get("sector"),
                is_ambiguous=symbol in cls._AMBIGUOUS_SYMBOLS,
            )
            dictionary.add(entry)
        return dictionary


def build_default_dictionary() -> TickerDictionary:
    """Build a minimal default dictionary with major tickers.

    In production, this is replaced by loading from the instruments table
    or a curated CSV. This exists for tests and bootstrapping.
    """
    dictionary = TickerDictionary()
    _defaults = [
        TickerEntry("AAPL", "Apple Inc.", ("Apple", "iPhone-maker", "AAPL"), "Technology"),
        TickerEntry("MSFT", "Microsoft Corporation", ("Microsoft", "MSFT"), "Technology"),
        TickerEntry("GOOGL", "Alphabet Inc.", ("Google", "Alphabet", "GOOGL"), "Technology"),
        TickerEntry("AMZN", "Amazon.com Inc.", ("Amazon", "AMZN"), "Consumer Discretionary"),
        TickerEntry("TSLA", "Tesla Inc.", ("Tesla", "TSLA"), "Consumer Discretionary"),
        TickerEntry("NVDA", "NVIDIA Corporation", ("NVIDIA", "Nvidia", "NVDA"), "Technology"),
        TickerEntry("META", "Meta Platforms Inc.", ("Meta", "Facebook", "META"), "Technology"),
        TickerEntry("JPM", "JPMorgan Chase & Co.", ("JPMorgan", "JP Morgan", "JPM"), "Financials"),
        TickerEntry("V", "Visa Inc.", ("Visa", "V"), "Financials", is_ambiguous=True),
        TickerEntry("T", "AT&T Inc.", ("AT&T", "ATT"), "Communication Services", is_ambiguous=True),
        TickerEntry(
            "BRK.B",
            "Berkshire Hathaway Inc.",
            ("Berkshire", "Berkshire Hathaway", "BRK.B", "BRK.A"),
            "Financials",
        ),
        TickerEntry("SPY", "SPDR S&P 500 ETF Trust", ("SPY", "S&P 500 ETF"), "ETF"),
        TickerEntry("QQQ", "Invesco QQQ Trust", ("QQQ", "Nasdaq ETF"), "ETF"),
        TickerEntry("IWM", "iShares Russell 2000 ETF", ("IWM", "Russell 2000 ETF"), "ETF"),
    ]
    for entry in _defaults:
        dictionary.add(entry)
    return dictionary
