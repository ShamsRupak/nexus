"""Accuracy and hallucination scoring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScoreResult:
    accuracy: float
    hallucination_rate: float
    grounded_claims: int
    total_claims: int


class AgentScorer:
    """Scores agent responses for accuracy and hallucinations."""

    def score(self, response: str, ground_truth: str) -> ScoreResult:
        # Placeholder: real implementation would use NLI model or LLM judge
        overlap = len(set(response.lower().split()) & set(ground_truth.lower().split()))
        total = max(len(ground_truth.lower().split()), 1)
        accuracy = min(overlap / total, 1.0)
        return ScoreResult(
            accuracy=round(accuracy, 3),
            hallucination_rate=round(1 - accuracy, 3),
            grounded_claims=overlap,
            total_claims=total,
        )
