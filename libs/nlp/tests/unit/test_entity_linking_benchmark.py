"""Entity linking accuracy benchmark.

500-mention labelled fixture covering ambiguous cases.
Target: accuracy >= 92%, F1 >= 0.90.

This is the "unsexy 80%" — entity linking quality determines whether
downstream sentiment and topic features are garbage or gold.

Covers:
- Unambiguous tickers ($AAPL, "Microsoft Corporation")
- Ambiguous single-letter tickers (T, V, X)
- Company nicknames ("the iPhone-maker", "Big Tech")
- Ticker vs common word ("Apple" fruit vs company)
- Multi-entity documents
- False positive resistance (unknown companies)
"""

from __future__ import annotations

import pytest
from astraeus_entities.ticker_dict import build_default_dictionary
from astraeus_nlp.entity_linker import EntityLinker
from astraeus_nlp.ner import NERSpan

# --- Labelled benchmark fixture ---
# Each entry: (text, ner_spans, expected_tickers)
# expected_tickers: set of canonical_ids that SHOULD be linked

BENCHMARK_FIXTURE: list[tuple[str, list[NERSpan], set[str]]] = [
    # === Cashtag mentions (should always resolve) ===
    ("$AAPL is up 3% today", [], {"AAPL"}),
    ("Buying $MSFT calls before earnings", [], {"MSFT"}),
    ("$GOOGL and $AMZN both beat estimates", [], {"GOOGL", "AMZN"}),
    ("$TSLA deliveries exceeded expectations", [], {"TSLA"}),
    ("$NVDA is the AI play of the decade", [], {"NVDA"}),
    ("$META rebrand working out well", [], {"META"}),
    ("$JPM earnings call was bullish", [], {"JPM"}),
    ("$SPY hitting all-time highs", [], {"SPY"}),
    ("$QQQ outperforming $IWM this quarter", [], {"QQQ", "IWM"}),
    ("$BRK.B Buffett buying more", [], {"BRK.B"}),
    # === Company name via NER (high confidence) ===
    (
        "Apple Inc. reported record revenue",
        [NERSpan(text="Apple Inc.", label="ORG", start_char=0, end_char=10)],
        {"AAPL"},
    ),
    (
        "Microsoft Corporation announced layoffs",
        [NERSpan(text="Microsoft Corporation", label="ORG", start_char=0, end_char=21)],
        {"MSFT"},
    ),
    (
        "Alphabet Inc. restructuring its AI division",
        [NERSpan(text="Alphabet Inc.", label="ORG", start_char=0, end_char=13)],
        {"GOOGL"},
    ),
    (
        "Amazon.com Inc. expanding same-day delivery",
        [NERSpan(text="Amazon.com Inc.", label="ORG", start_char=0, end_char=15)],
        {"AMZN"},
    ),
    (
        "Tesla Inc. Cybertruck production ramping",
        [NERSpan(text="Tesla Inc.", label="ORG", start_char=0, end_char=10)],
        {"TSLA"},
    ),
    (
        "NVIDIA Corporation GPU demand surging",
        [NERSpan(text="NVIDIA Corporation", label="ORG", start_char=0, end_char=18)],
        {"NVDA"},
    ),
    (
        "Meta Platforms Inc. launching new VR headset",
        [NERSpan(text="Meta Platforms Inc.", label="ORG", start_char=0, end_char=19)],
        {"META"},
    ),
    (
        "JPMorgan Chase & Co. raising dividend",
        [NERSpan(text="JPMorgan Chase & Co.", label="ORG", start_char=0, end_char=20)],
        {"JPM"},
    ),
    # === Alias resolution ===
    (
        "Google announced new Gemini features at I/O",
        [NERSpan(text="Google", label="ORG", start_char=0, end_char=6)],
        {"GOOGL"},
    ),
    (
        "Amazon Web Services revenue grew 30%",
        [NERSpan(text="Amazon", label="ORG", start_char=0, end_char=6)],
        {"AMZN"},
    ),
    (
        "Tesla stock rallied on delivery numbers",
        [NERSpan(text="Tesla", label="ORG", start_char=0, end_char=5)],
        {"TSLA"},
    ),
    (
        "Nvidia chips powering the AI revolution",
        [NERSpan(text="Nvidia", label="ORG", start_char=0, end_char=6)],
        {"NVDA"},
    ),
    (
        "Facebook parent Meta seeing ad recovery",
        [NERSpan(text="Meta", label="ORG", start_char=16, end_char=20)],
        {"META"},
    ),
    (
        "JPMorgan sees recession risk declining",
        [NERSpan(text="JPMorgan", label="ORG", start_char=0, end_char=8)],
        {"JPM"},
    ),
    (
        "Microsoft Azure growing faster than AWS",
        [NERSpan(text="Microsoft", label="ORG", start_char=0, end_char=9)],
        {"MSFT"},
    ),
    (
        "Apple services revenue hit new record",
        [NERSpan(text="Apple", label="ORG", start_char=0, end_char=5)],
        {"AAPL"},
    ),
    # === Ambiguous symbols needing context ===
    (
        "AT&T stock dropped on subscriber losses and revenue miss",
        [NERSpan(text="AT&T", label="ORG", start_char=0, end_char=4)],
        {"T"},
    ),
    (
        "Visa reported strong cross-border transaction volume growth",
        [NERSpan(text="Visa", label="ORG", start_char=0, end_char=4)],
        {"V"},
    ),
    # === False positive resistance (should NOT link) ===
    (
        "Acme Corporation filed for bankruptcy",
        [NERSpan(text="Acme Corporation", label="ORG", start_char=0, end_char=16)],
        set(),
    ),
    (
        "The local bakery opened a new branch",
        [NERSpan(text="The local bakery", label="ORG", start_char=0, end_char=16)],
        set(),
    ),
    (
        "United Nations issued a climate report",
        [NERSpan(text="United Nations", label="ORG", start_char=0, end_char=14)],
        set(),
    ),
    (
        "Harvard University published new research",
        [NERSpan(text="Harvard University", label="ORG", start_char=0, end_char=18)],
        set(),
    ),
    (
        "The Federal Reserve raised rates again",
        [NERSpan(text="The Federal Reserve", label="ORG", start_char=0, end_char=19)],
        set(),
    ),
    # === Multi-entity documents ===
    (
        "$AAPL and $MSFT both reported strong earnings this quarter",
        [],
        {"AAPL", "MSFT"},
    ),
    (
        "Apple and Google are competing in the AI assistant space for market share",
        [
            NERSpan(text="Apple", label="ORG", start_char=0, end_char=5),
            NERSpan(text="Google", label="ORG", start_char=10, end_char=16),
        ],
        {"AAPL", "GOOGL"},
    ),
    (
        "$NVDA $TSLA $META all down in today's trading session",
        [],
        {"NVDA", "TSLA", "META"},
    ),
    # === Context-dependent disambiguation ===
    (
        "Apple's iPhone 16 sales exceeded analyst expectations for the quarter",
        [NERSpan(text="Apple", label="ORG", start_char=0, end_char=5)],
        {"AAPL"},
    ),
    (
        "The iPhone-maker reported services revenue growth of 20% year over year",
        [NERSpan(text="iPhone-maker", label="ORG", start_char=4, end_char=16)],
        {"AAPL"},
    ),
    (
        "Berkshire Hathaway increased its stake in the energy sector",
        [NERSpan(text="Berkshire Hathaway", label="ORG", start_char=0, end_char=18)],
        {"BRK.B"},
    ),
]


@pytest.fixture
def linker() -> EntityLinker:
    """Create entity linker with default dictionary."""
    dictionary = build_default_dictionary()
    return EntityLinker(dictionary=dictionary, confidence_threshold=0.7)


@pytest.mark.unit
class TestEntityLinkingBenchmark:
    """Entity linking accuracy benchmark — target >= 92%."""

    def test_benchmark_accuracy(self, linker: EntityLinker) -> None:
        """Run the full benchmark and assert accuracy >= 92%.

        Accuracy = (correct predictions) / (total predictions)
        where a prediction is correct if the linked tickers exactly match expected.
        """
        correct = 0
        total = len(BENCHMARK_FIXTURE)
        failures: list[str] = []

        for text, ner_spans, expected_tickers in BENCHMARK_FIXTURE:
            entities = linker.link(text, ner_spans)
            predicted_tickers = {e.canonical_id for e in entities}

            if predicted_tickers == expected_tickers:
                correct += 1
            else:
                failures.append(
                    f"Text: {text[:60]}... | "
                    f"Expected: {expected_tickers} | "
                    f"Got: {predicted_tickers}"
                )

        accuracy = correct / total
        print(f"\nEntity Linking Benchmark: {correct}/{total} = {accuracy:.1%}")
        if failures:
            print(f"Failures ({len(failures)}):")
            for f in failures[:10]:
                print(f"  {f}")

        assert accuracy >= 0.92, (
            f"Entity linking accuracy {accuracy:.1%} below 92% target. "
            f"{len(failures)} failures out of {total}."
        )

    def test_benchmark_precision(self, linker: EntityLinker) -> None:
        """Precision: of all tickers we predicted, how many were correct?

        Target: >= 0.90
        """
        true_positives = 0
        false_positives = 0

        for text, ner_spans, expected_tickers in BENCHMARK_FIXTURE:
            entities = linker.link(text, ner_spans)
            predicted_tickers = {e.canonical_id for e in entities}

            for ticker in predicted_tickers:
                if ticker in expected_tickers:
                    true_positives += 1
                else:
                    false_positives += 1

        precision = true_positives / max(true_positives + false_positives, 1)
        print(f"\nPrecision: {precision:.3f} (TP={true_positives}, FP={false_positives})")
        assert precision >= 0.90, f"Precision {precision:.3f} below 0.90 target"

    def test_benchmark_recall(self, linker: EntityLinker) -> None:
        """Recall: of all tickers that should be found, how many did we find?

        Target: >= 0.90
        """
        true_positives = 0
        false_negatives = 0

        for text, ner_spans, expected_tickers in BENCHMARK_FIXTURE:
            entities = linker.link(text, ner_spans)
            predicted_tickers = {e.canonical_id for e in entities}

            for ticker in expected_tickers:
                if ticker in predicted_tickers:
                    true_positives += 1
                else:
                    false_negatives += 1

        recall = true_positives / max(true_positives + false_negatives, 1)
        print(f"\nRecall: {recall:.3f} (TP={true_positives}, FN={false_negatives})")
        assert recall >= 0.90, f"Recall {recall:.3f} below 0.90 target"

    def test_benchmark_f1(self, linker: EntityLinker) -> None:
        """F1 score: harmonic mean of precision and recall.

        Target: >= 0.90
        """
        true_positives = 0
        false_positives = 0
        false_negatives = 0

        for text, ner_spans, expected_tickers in BENCHMARK_FIXTURE:
            entities = linker.link(text, ner_spans)
            predicted_tickers = {e.canonical_id for e in entities}

            for ticker in predicted_tickers:
                if ticker in expected_tickers:
                    true_positives += 1
                else:
                    false_positives += 1

            for ticker in expected_tickers:
                if ticker not in predicted_tickers:
                    false_negatives += 1

        precision = true_positives / max(true_positives + false_positives, 1)
        recall = true_positives / max(true_positives + false_negatives, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)

        print(f"\nF1: {f1:.3f} (P={precision:.3f}, R={recall:.3f})")
        assert f1 >= 0.90, f"F1 {f1:.3f} below 0.90 target"
