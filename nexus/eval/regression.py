"""Regression test suite runner with baseline comparison and CI output."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CaseStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class CaseResult(BaseModel):
    name: str
    prompt: str
    status: CaseStatus
    expected: dict[str, Any]
    actual: dict[str, Any] = {}
    error: str | None = None
    latency_ms: float = 0.0


class RegressionReport(BaseModel):
    run_id: str
    timestamp: datetime = datetime.utcnow()
    total: int
    passed: int
    failed: int
    errors: int
    pass_rate: float
    results: list[CaseResult] = []

    @classmethod
    def from_results(cls, run_id: str, results: list[CaseResult]) -> RegressionReport:
        total = len(results)
        passed = sum(1 for r in results if r.status == CaseStatus.PASSED)
        failed = sum(1 for r in results if r.status == CaseStatus.FAILED)
        errors = sum(1 for r in results if r.status == CaseStatus.ERROR)
        return cls(
            run_id=run_id,
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            pass_rate=round(passed / total, 4) if total else 0.0,
            results=results,
        )


@dataclass
class RegressionDiff:
    """Comparison between two regression reports."""

    baseline_run_id: str
    current_run_id: str
    regressed: list[str]  # case names that were passing and are now failing
    improved: list[str]  # case names that were failing and are now passing
    stable_pass: list[str]  # still passing
    stable_fail: list[str]  # still failing

    @property
    def net_change(self) -> int:
        return len(self.improved) - len(self.regressed)

    def to_dict(self) -> dict:
        return {
            "baseline_run_id": self.baseline_run_id,
            "current_run_id": self.current_run_id,
            "regressed": self.regressed,
            "improved": self.improved,
            "stable_pass": self.stable_pass,
            "stable_fail": self.stable_fail,
            "net_change": self.net_change,
        }


class RegressionRunner:
    """Runs a suite of regression cases against the Nexus pipeline."""

    def __init__(self) -> None:
        self._cases: list[dict[str, Any]] = []

    def add_case(self, name: str, prompt: str, expected: dict[str, Any]) -> None:
        """Add a test case.

        Args:
            name: Unique case identifier.
            prompt: Input prompt to classify and plan.
            expected: Dict with optional keys:
                - intent: expected IntentType value (str)
                - answer_contains: list of substrings expected in response
                - requires_approval: bool
        """
        self._cases.append({"name": name, "prompt": prompt, "expected": expected})

    def load_cases(self, cases: list[dict[str, Any]]) -> None:
        """Bulk-load cases from a list of dicts (e.g. parsed from YAML)."""
        for c in cases:
            self.add_case(c["name"], c["prompt"], c.get("expected", {}))

    async def run_all(self) -> RegressionReport:
        """Run all registered cases and return a :class:`RegressionReport`."""
        import time
        import uuid

        from nexus.core.executor import ApprovalRequiredError, PlanExecutor
        from nexus.core.intent import IntentClassifier
        from nexus.core.planner import PlanDecomposer

        run_id = str(uuid.uuid4())[:8]
        classifier = IntentClassifier()
        planner = PlanDecomposer()
        executor = PlanExecutor()
        results: list[CaseResult] = []

        for case in self._cases:
            name = case["name"]
            prompt = case["prompt"]
            expected = case["expected"]
            start = time.monotonic()

            try:
                intent = await classifier.classify(prompt)
                plan = await planner.decompose(intent)

                actual: dict[str, Any] = {
                    "intent": intent.intent_type.value,
                    "requires_approval": plan.requires_approval,
                    "step_count": len(plan.steps),
                }

                try:
                    response = await executor.execute(plan)
                    actual["answer"] = response.answer or ""
                except ApprovalRequiredError:
                    actual["answer"] = ""
                    actual["requires_approval"] = True

                latency = (time.monotonic() - start) * 1000

                # Evaluate against expectations
                status = _evaluate(actual, expected)
                results.append(
                    CaseResult(
                        name=name,
                        prompt=prompt,
                        status=status,
                        expected=expected,
                        actual=actual,
                        latency_ms=round(latency, 2),
                    )
                )

            except Exception as exc:
                latency = (time.monotonic() - start) * 1000
                logger.error("Regression case '%s' raised: %s", name, exc)
                results.append(
                    CaseResult(
                        name=name,
                        prompt=prompt,
                        status=CaseStatus.ERROR,
                        expected=expected,
                        error=str(exc),
                        latency_ms=round(latency, 2),
                    )
                )

        return RegressionReport.from_results(run_id, results)

    @staticmethod
    def compare_to_baseline(
        current: RegressionReport, baseline: RegressionReport
    ) -> RegressionDiff:
        """Compare current report to baseline and identify regressions/improvements."""
        baseline_map = {r.name: r.status for r in baseline.results}
        current_map = {r.name: r.status for r in current.results}

        regressed, improved, stable_pass, stable_fail = [], [], [], []

        for name, cur_status in current_map.items():
            base_status = baseline_map.get(name)
            if base_status == CaseStatus.PASSED and cur_status != CaseStatus.PASSED:
                regressed.append(name)
            elif base_status != CaseStatus.PASSED and cur_status == CaseStatus.PASSED:
                improved.append(name)
            elif cur_status == CaseStatus.PASSED:
                stable_pass.append(name)
            else:
                stable_fail.append(name)

        return RegressionDiff(
            baseline_run_id=baseline.run_id,
            current_run_id=current.run_id,
            regressed=sorted(regressed),
            improved=sorted(improved),
            stable_pass=sorted(stable_pass),
            stable_fail=sorted(stable_fail),
        )

    def export_json(self, report: RegressionReport) -> str:
        return report.model_dump_json(indent=2)


def _evaluate(actual: dict, expected: dict) -> CaseStatus:
    """Check actual result against expectations. Returns PASSED or FAILED."""
    if "intent" in expected:
        if actual.get("intent") != expected["intent"]:
            return CaseStatus.FAILED

    if "requires_approval" in expected:
        if actual.get("requires_approval") != expected["requires_approval"]:
            return CaseStatus.FAILED

    if "answer_contains" in expected:
        answer = (actual.get("answer") or "").lower()
        for substring in expected["answer_contains"]:
            if substring.lower() not in answer:
                return CaseStatus.FAILED

    return CaseStatus.PASSED
