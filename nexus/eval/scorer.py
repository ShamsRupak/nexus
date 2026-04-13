"""Agent output quality scoring — accuracy, completeness, format."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ScoreResult:
    accuracy: float
    completeness: float
    format_score: float
    overall: float

    def __post_init__(self) -> None:
        # Ensure all scores in [0, 1]
        for field_name in ("accuracy", "completeness", "format_score", "overall"):
            v = getattr(self, field_name)
            object.__setattr__(self, field_name, round(max(0.0, min(1.0, v)), 4))


def accuracy_score(response: str, ground_truth: str) -> float:
    """Semantic overlap between response and ground truth (Jaccard on tokens).

    Returns a float in [0.0, 1.0].  Identical strings → 1.0.
    Completely disjoint vocabularies → 0.0.

    If sentence-transformers is available, cosine similarity of embeddings
    is used instead, which is more semantically aware.
    """
    if not response and not ground_truth:
        return 1.0
    if not response or not ground_truth:
        return 0.0
    if response.strip().lower() == ground_truth.strip().lower():
        return 1.0

    # Try embedding-based cosine similarity first
    try:
        return _embedding_similarity(response, ground_truth)
    except Exception:
        pass

    # Jaccard fallback
    r_tokens = set(_tokenise(response))
    g_tokens = set(_tokenise(ground_truth))
    if not r_tokens and not g_tokens:
        return 1.0
    intersection = r_tokens & g_tokens
    union = r_tokens | g_tokens
    return round(len(intersection) / len(union), 4) if union else 0.0


def completeness_score(response: str, expected_fields: list[str]) -> float:
    """Return the fraction of expected_fields that appear in the response text.

    A field is "present" if it or a normalised version of it appears in the
    response (case-insensitive substring match).
    """
    if not expected_fields:
        return 1.0
    if not response:
        return 0.0

    response_lower = response.lower()
    found = sum(1 for f in expected_fields if f.lower() in response_lower)
    return round(found / len(expected_fields), 4)


def format_score(response: str, expected_format: str) -> float:
    """Check whether the response conforms to an expected format.

    Supported expected_format values:
        "json"      — valid JSON
        "table"     — contains | or TAB-separated lines
        "list"      — contains newline-separated bullet items
        "text"      — any non-empty string
    """
    if not response:
        return 0.0

    fmt = expected_format.lower()

    if fmt == "json":
        try:
            json.loads(response)
            return 1.0
        except json.JSONDecodeError:
            # Partial credit: does it look JSON-ish?
            return 0.3 if response.strip().startswith(("{", "[")) else 0.0

    if fmt == "table":
        lines = [l for l in response.splitlines() if l.strip()]
        tabular = sum(1 for l in lines if "|" in l or "\t" in l)
        return round(tabular / max(len(lines), 1), 4)

    if fmt == "list":
        bullet_lines = re.findall(r"^\s*[-*•\d+\.]", response, re.MULTILINE)
        lines = [l for l in response.splitlines() if l.strip()]
        return round(len(bullet_lines) / max(len(lines), 1), 4)

    if fmt == "text":
        return 1.0 if response.strip() else 0.0

    # Unknown format — pass through
    return 1.0


def score_response(
    response: str,
    ground_truth: str,
    expected_fields: list[str] | None = None,
    expected_format: str = "text",
) -> ScoreResult:
    """Aggregate scorer that returns a ScoreResult with all three dimensions."""
    acc = accuracy_score(response, ground_truth)
    comp = completeness_score(response, expected_fields or [])
    fmt = format_score(response, expected_format)
    overall = round((acc + comp + fmt) / 3, 4)
    return ScoreResult(accuracy=acc, completeness=comp, format_score=fmt, overall=overall)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tokenise(text: str) -> list[str]:
    """Lower-case, strip punctuation, split on whitespace."""
    return re.findall(r"\b[a-z0-9]+\b", text.lower())


def _embedding_similarity(a: str, b: str) -> float:
    """Cosine similarity using sentence-transformers if available."""
    from sentence_transformers import SentenceTransformer
    import numpy as np

    model = SentenceTransformer("all-MiniLM-L6-v2")
    vecs = model.encode([a, b], normalize_embeddings=True)
    return float(np.dot(vecs[0], vecs[1]))
