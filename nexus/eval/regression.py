"""Regression test runner for agent behaviour."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RegressionCase:
    prompt: str
    expected_intent: str
    expected_answer_contains: list[str]


class RegressionRunner:
    """Runs regression test suites against a live agent pipeline."""

    def __init__(self, cases: list[RegressionCase]) -> None:
        self._cases = cases

    async def run(self, agent_fn) -> dict:
        passed = 0
        failed = 0
        for case in self._cases:
            try:
                result = await agent_fn(case.prompt)
                answer = (result.answer or "").lower()
                ok = all(kw.lower() in answer for kw in case.expected_answer_contains)
                if ok:
                    passed += 1
                else:
                    failed += 1
                    logger.warning("Regression FAIL: %s", case.prompt)
            except Exception as exc:
                failed += 1
                logger.error("Regression ERROR for %s: %s", case.prompt, exc)
        return {"passed": passed, "failed": failed, "total": len(self._cases)}
