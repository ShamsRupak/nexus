"""Citation verification against source documents."""

from __future__ import annotations

import re


class CitationVerifier:
    """Verifies that claims in a response are grounded in source documents."""

    def verify(self, response: str, sources: list[str]) -> dict:
        sentences = re.split(r"[.!?]+", response)
        verified = 0
        for sentence in sentences:
            if any(
                any(word in src.lower() for word in sentence.lower().split() if len(word) > 4)
                for src in sources
            ):
                verified += 1
        total = max(len([s for s in sentences if s.strip()]), 1)
        return {
            "verified_sentences": verified,
            "total_sentences": total,
            "citation_rate": round(verified / total, 3),
        }
