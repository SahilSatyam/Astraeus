"""Faithfulness eval — claim → citation grounding scorer.

For each agent emitting cited findings, scores whether the claim
is entailed by the cited chunk text.

Scoring: {entailed, neutral, contradicted}
Threshold: ≥ 90% entailed across sampled runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("astraeus.agent_runtime.evals.faithfulness")


@dataclass(frozen=True, slots=True)
class FaithfulnessScore:
    """Score for a single claim-citation pair."""

    claim: str
    chunk_id: str
    chunk_text: str
    label: str  # "entailed", "neutral", "contradicted"
    confidence: float = 0.0


@dataclass(slots=True)
class FaithfulnessResult:
    """Aggregate faithfulness result for a run."""

    total_claims: int = 0
    entailed: int = 0
    neutral: int = 0
    contradicted: int = 0
    scores: list[FaithfulnessScore] = field(default_factory=list)

    @property
    def entailment_rate(self) -> float:
        if self.total_claims == 0:
            return 1.0
        return self.entailed / self.total_claims

    @property
    def passes_threshold(self) -> bool:
        """Passes if ≥ 90% of claims are entailed."""
        return self.entailment_rate >= 0.90


def evaluate_faithfulness(
    output: dict[str, Any],
    chunk_lookup: dict[str, str] | None = None,
) -> FaithfulnessResult:
    """Evaluate faithfulness of cited claims in agent output.

    For each finding with citations, checks if the claim text is
    supported by the cited chunk text using simple heuristics.
    In production, this uses a separate frontier LLM judge.

    Args:
        output: Agent output containing findings with citations.
        chunk_lookup: Mapping of chunk_id → chunk text for verification.

    Returns:
        FaithfulnessResult with per-claim scores.
    """
    result = FaithfulnessResult()
    chunk_lookup = chunk_lookup or {}

    # Extract findings from various output shapes
    findings = _extract_findings(output)

    for finding in findings:
        claim = finding.get("claim", "")
        citations = finding.get("citations", [])

        if not claim or not citations:
            continue

        for citation in citations:
            if not isinstance(citation, dict):
                continue

            chunk_id = citation.get("chunk_id", "")
            chunk_text = chunk_lookup.get(chunk_id, citation.get("quoted_text", ""))

            result.total_claims += 1

            if not chunk_text:
                # Can't verify without chunk text — mark neutral
                result.neutral += 1
                result.scores.append(
                    FaithfulnessScore(
                        claim=claim,
                        chunk_id=chunk_id,
                        chunk_text="",
                        label="neutral",
                        confidence=0.5,
                    )
                )
                continue

            # Simple heuristic: check keyword overlap
            label = _score_entailment(claim, chunk_text)
            if label == "entailed":
                result.entailed += 1
            elif label == "contradicted":
                result.contradicted += 1
            else:
                result.neutral += 1

            result.scores.append(
                FaithfulnessScore(
                    claim=claim,
                    chunk_id=chunk_id,
                    chunk_text=chunk_text[:200],
                    label=label,
                    confidence=0.7,
                )
            )

    return result


def _extract_findings(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract findings from various output shapes."""
    findings: list[dict[str, Any]] = []

    # Direct findings
    if "findings" in output:
        findings.extend(output["findings"])

    # Nested in research
    research = output.get("research", {})
    if isinstance(research, dict) and "findings" in research:
        findings.extend(research["findings"])

    # Nested in sentiment drivers
    sentiment = output.get("sentiment", {})
    if isinstance(sentiment, dict) and "drivers" in sentiment:
        findings.extend(sentiment["drivers"])

    return findings


def _score_entailment(claim: str, chunk_text: str) -> str:
    """Simple heuristic entailment scoring.

    In production, this is replaced by an LLM judge call.
    For the eval harness MVP, we use keyword overlap.
    """
    claim_lower = claim.lower()
    chunk_lower = chunk_text.lower()

    # Extract significant words (>4 chars, not stopwords)
    claim_words = {w for w in claim_lower.split() if len(w) > 4}
    chunk_words = {w for w in chunk_lower.split() if len(w) > 4}

    if not claim_words:
        return "neutral"

    overlap = claim_words & chunk_words
    overlap_ratio = len(overlap) / len(claim_words)

    if overlap_ratio >= 0.4:
        return "entailed"
    if overlap_ratio >= 0.1:
        return "neutral"
    return "neutral"  # Conservative: don't mark contradicted without LLM
