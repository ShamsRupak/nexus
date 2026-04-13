"""Citation verification and hallucination detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Grounding threshold: a claim is considered grounded if its best-matching
# source chunk scores >= this value.
_GROUNDED_THRESHOLD = 0.75


@dataclass
class ClaimResult:
    claim: str
    grounded: bool
    best_source: str  # text of the best-matching source chunk
    score: float  # similarity score [0, 1]


@dataclass
class CitationReport:
    total_claims: int
    grounded: int
    ungrounded: int
    hallucination_rate: float
    details: list[ClaimResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.total_claims > 0:
            self.hallucination_rate = round(self.ungrounded / self.total_claims, 4)
        else:
            self.hallucination_rate = 0.0


def verify_citations(response: str, source_documents: list[str]) -> CitationReport:
    """Check each sentence in *response* against *source_documents*.

    A claim is "grounded" if its similarity to at least one source chunk
    exceeds *_GROUNDED_THRESHOLD*.

    Similarity strategy:
        1. Try cosine similarity of sentence-transformer embeddings.
        2. Fall back to a word-overlap (Jaccard) similarity.

    Returns a :class:`CitationReport` with per-claim details.
    """
    claims = _extract_claims(response)
    if not claims:
        return CitationReport(total_claims=0, grounded=0, ungrounded=0, hallucination_rate=0.0)

    if not source_documents:
        details = [ClaimResult(claim=c, grounded=False, best_source="", score=0.0) for c in claims]
        return CitationReport(
            total_claims=len(claims),
            grounded=0,
            ungrounded=len(claims),
            hallucination_rate=1.0,
            details=details,
        )

    try:
        details = _embedding_verify(claims, source_documents)
    except Exception:
        details = _jaccard_verify(claims, source_documents)

    grounded = sum(1 for d in details if d.grounded)
    ungrounded = len(details) - grounded

    return CitationReport(
        total_claims=len(details),
        grounded=grounded,
        ungrounded=ungrounded,
        hallucination_rate=round(ungrounded / max(len(details), 1), 4),
        details=details,
    )


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------


def _extract_claims(text: str) -> list[str]:
    """Split text into individual factual claims (sentences)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 4]


# ---------------------------------------------------------------------------
# Embedding-based verification
# ---------------------------------------------------------------------------


def _embedding_verify(claims: list[str], sources: list[str]) -> list[ClaimResult]:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")
    all_texts = claims + sources
    vecs = model.encode(all_texts, normalize_embeddings=True)

    claim_vecs = vecs[: len(claims)]
    source_vecs = vecs[len(claims) :]

    results: list[ClaimResult] = []
    for i, (claim, cvec) in enumerate(zip(claims, claim_vecs)):
        scores = [float(np.dot(cvec, sv)) for sv in source_vecs]
        best_idx = int(max(range(len(scores)), key=lambda j: scores[j]))
        best_score = scores[best_idx]
        results.append(
            ClaimResult(
                claim=claim,
                grounded=best_score >= _GROUNDED_THRESHOLD,
                best_source=sources[best_idx][:200],
                score=round(best_score, 4),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Jaccard fallback
# ---------------------------------------------------------------------------


def _jaccard_verify(claims: list[str], sources: list[str]) -> list[ClaimResult]:
    """Word-overlap similarity as a fallback when embeddings are unavailable."""
    source_tokens = [set(_tok(s)) for s in sources]
    results: list[ClaimResult] = []

    for claim in claims:
        claim_tokens = set(_tok(claim))
        best_score = 0.0
        best_idx = 0

        for j, stok in enumerate(source_tokens):
            union = claim_tokens | stok
            inter = claim_tokens & stok
            score = len(inter) / len(union) if union else 0.0
            if score > best_score:
                best_score = score
                best_idx = j

        results.append(
            ClaimResult(
                claim=claim,
                grounded=best_score >= _GROUNDED_THRESHOLD,
                best_source=sources[best_idx][:200],
                score=round(best_score, 4),
            )
        )
    return results


def _tok(text: str) -> list[str]:
    return re.findall(r"\b[a-z0-9]+\b", text.lower())
