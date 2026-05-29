"""Named Entity Recognition for financial text.

Uses spaCy with a finance-tuned model for NER. Extracts:
- ORG entities (companies)
- PERSON entities (executives, analysts)
- MONEY/PERCENT entities (financial figures)

The NER output feeds into the entity linker for ticker resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import spacy

logger = structlog.get_logger("astraeus.nlp.ner")


@dataclass(frozen=True, slots=True)
class NERSpan:
    """A single NER-detected entity span."""

    text: str
    label: str  # ORG, PERSON, MONEY, PERCENT, GPE, etc.
    start_char: int
    end_char: int
    confidence: float = 1.0  # spaCy doesn't provide confidence natively


class FinanceNER:
    """Finance-aware NER using spaCy.

    Loads a spaCy model (default: en_core_web_sm, upgrade to en_core_web_trf
    for better accuracy at the cost of speed).

    Filters entities to those relevant for financial text analysis.
    """

    # Entity labels we care about for finance
    _RELEVANT_LABELS = frozenset({"ORG", "PERSON", "MONEY", "PERCENT", "GPE", "PRODUCT"})

    def __init__(self, model_name: str = "en_core_web_sm") -> None:
        self._model_name = model_name
        self._nlp: spacy.Language | None = None

    def _load_model(self) -> spacy.Language:
        """Lazy-load the spaCy model."""
        if self._nlp is None:
            import spacy

            try:
                self._nlp = spacy.load(self._model_name)
            except OSError:
                logger.warning(
                    "spacy_model_not_found",
                    model=self._model_name,
                    msg="Falling back to en_core_web_sm. Run: python -m spacy download en_core_web_sm",
                )
                self._nlp = spacy.load("en_core_web_sm")

            # Disable unused pipeline components for speed
            disabled = [
                pipe
                for pipe in self._nlp.pipe_names
                if pipe not in ("ner", "tok2vec", "transformer")
            ]
            for pipe in disabled:
                if pipe in self._nlp.pipe_names:
                    self._nlp.disable_pipe(pipe)

        return self._nlp

    def extract(self, text: str) -> list[NERSpan]:
        """Extract named entities from text.

        Returns only entities with labels relevant to financial analysis.
        """
        nlp = self._load_model()
        doc = nlp(text)

        spans: list[NERSpan] = []
        for ent in doc.ents:
            if ent.label_ in self._RELEVANT_LABELS:
                spans.append(
                    NERSpan(
                        text=ent.text,
                        label=ent.label_,
                        start_char=ent.start_char,
                        end_char=ent.end_char,
                    )
                )

        return spans

    def extract_batch(self, texts: list[str]) -> list[list[NERSpan]]:
        """Batch NER extraction using spaCy's pipe() for efficiency."""
        nlp = self._load_model()
        results: list[list[NERSpan]] = []

        for doc in nlp.pipe(texts, batch_size=32):
            spans: list[NERSpan] = []
            for ent in doc.ents:
                if ent.label_ in self._RELEVANT_LABELS:
                    spans.append(
                        NERSpan(
                            text=ent.text,
                            label=ent.label_,
                            start_char=ent.start_char,
                            end_char=ent.end_char,
                        )
                    )
            results.append(spans)

        return results
