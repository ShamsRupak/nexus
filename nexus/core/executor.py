"""Plan execution engine with dependency resolution and human-in-the-loop."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from nexus.config import get_settings
from nexus.core.types import (
    AgentResponse,
    Plan,
    Step,
    StepResult,
    StepStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Prometheus metrics — gracefully degrade if not installed
# ---------------------------------------------------------------------------
try:
    from prometheus_client import Counter, Histogram

    _step_duration = Histogram(
        "nexus_step_execution_duration_seconds",
        "Duration of individual step execution",
        ["tool"],
    )
    _step_success = Counter(
        "nexus_step_success_total",
        "Total successful step executions",
        ["tool"],
    )
    _step_failure = Counter(
        "nexus_step_failure_total",
        "Total failed step executions",
        ["tool"],
    )
    _METRICS_AVAILABLE = True
except Exception:
    _METRICS_AVAILABLE = False
    logger.debug("Prometheus metrics not available")


class ApprovalRequiredError(Exception):
    """Raised when a plan requires human approval before execution."""

    def __init__(self, plan: Plan) -> None:
        self.plan = plan
        super().__init__(f"Plan {plan.id} requires human approval before execution")


class PlanExecutor:
    """Executes Plans by respecting topological dependency order."""

    def __init__(
        self,
        tool_registry: dict[str, Any] | None = None,
    ) -> None:
        self._settings = get_settings()
        # tool_registry maps tool name -> async callable
        self._tools: dict[str, Any] = tool_registry or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, plan: Plan) -> AgentResponse:
        """Execute a plan. Raises ApprovalRequiredError if approval needed."""
        if plan.requires_approval:
            # Mark all steps as awaiting approval so callers can inspect state
            for step in plan.steps:
                step.status = StepStatus.AWAITING_APPROVAL
            raise ApprovalRequiredError(plan)

        return await self._run_plan(plan)

    async def approve_and_execute(self, plan: Plan) -> AgentResponse:
        """Skip approval gate and execute directly (called after human sign-off)."""
        # Reset approval status before execution
        for step in plan.steps:
            if step.status == StepStatus.AWAITING_APPROVAL:
                step.status = StepStatus.PENDING
        return await self._run_plan(plan)

    # ------------------------------------------------------------------
    # Internal execution logic
    # ------------------------------------------------------------------

    async def _run_plan(self, plan: Plan) -> AgentResponse:
        start_ms = time.monotonic() * 1000
        context: dict[str, Any] = {}
        actions_taken: list[dict] = []
        total_tokens: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total": 0}

        # Steps are already topologically sorted by the planner
        for step in plan.steps:
            # Skip if a dependency already failed
            if self._has_failed_dependency(step, plan):
                step.status = StepStatus.FAILED
                step.error = "Skipped — dependency failed"
                logger.warning("Step %s skipped due to failed dependency", step.id)
                continue

            result = await self._execute_step_with_retry(step, context)

            # Update context for downstream steps
            context[step.id] = result.output

            # Accumulate token usage
            for k, v in result.token_usage.items():
                total_tokens[k] = total_tokens.get(k, 0) + v

            if result.success:
                actions_taken.append(
                    {
                        "step_id": step.id,
                        "tool": step.tool,
                        "description": step.description,
                        "status": "completed",
                    }
                )
            else:
                actions_taken.append(
                    {
                        "step_id": step.id,
                        "tool": step.tool,
                        "description": step.description,
                        "status": "failed",
                        "error": result.error,
                    }
                )

        latency_ms = time.monotonic() * 1000 - start_ms
        answer = self._extract_answer(plan, context)

        return AgentResponse(
            plan_id=plan.id,
            answer=answer,
            data={"step_outputs": {k: str(v)[:1000] for k, v in context.items()}},
            actions_taken=actions_taken,
            trace_id=plan.trace_id,
            latency_ms=round(latency_ms, 2),
            token_usage=total_tokens,
        )

    async def _execute_step_with_retry(self, step: Step, context: dict) -> StepResult:
        """Execute a step with exponential-backoff retries."""
        max_retries = self._settings.max_retries
        timeout = self._settings.step_timeout_seconds
        last_error = ""

        for attempt in range(max_retries):
            try:
                result = await asyncio.wait_for(
                    self._execute_step(step, context),
                    timeout=timeout,
                )
                return result
            except TimeoutError:
                last_error = f"Step timed out after {timeout}s"
                step.error = last_error
                logger.warning("Step %s timed out (attempt %d)", step.id, attempt + 1)
            except Exception as exc:
                last_error = str(exc)
                step.error = last_error
                logger.warning("Step %s failed (attempt %d): %s", step.id, attempt + 1, exc)

            if attempt < max_retries - 1:
                backoff = 2**attempt
                await asyncio.sleep(backoff)

        # All retries exhausted
        step.status = StepStatus.FAILED
        step.completed_at = datetime.utcnow()
        if _METRICS_AVAILABLE:
            try:
                _step_failure.labels(tool=step.tool).inc()
            except Exception:
                pass
        return StepResult(step_id=step.id, success=False, error=last_error)

    async def _execute_step(self, step: Step, context: dict) -> StepResult:
        """Execute a single step, calling the appropriate tool."""
        step.status = StepStatus.RUNNING
        step.started_at = datetime.utcnow()
        timer_start = time.monotonic()

        try:
            tool_fn = self._tools.get(step.tool) or self._default_tool_handler
            output = await tool_fn(step, context)

            step.status = StepStatus.COMPLETED
            step.result = output
            step.completed_at = datetime.utcnow()

            elapsed = time.monotonic() - timer_start
            if _METRICS_AVAILABLE:
                try:
                    _step_duration.labels(tool=step.tool).observe(elapsed)
                    _step_success.labels(tool=step.tool).inc()
                except Exception:
                    pass

            return StepResult(step_id=step.id, success=True, output=output)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            step.completed_at = datetime.utcnow()
            raise

    async def _default_tool_handler(self, step: Step, context: dict) -> Any:
        """Stub handler used when no real tool is registered."""
        logger.debug("Stub tool handler called for tool=%s step=%s", step.tool, step.id)
        return {"stub": True, "tool": step.tool, "params": step.params}

    def _has_failed_dependency(self, step: Step, plan: Plan) -> bool:
        for dep_id in step.depends_on:
            dep = plan.get_step(dep_id)
            if dep and dep.status == StepStatus.FAILED:
                return True
        return False

    def _extract_answer(self, plan: Plan, context: dict) -> str | None:
        """Extract the final natural-language answer from the last synthesis step."""
        for step in reversed(plan.steps):
            if step.tool == "llm_synthesize" and step.status == StepStatus.COMPLETED:
                result = context.get(step.id)
                if isinstance(result, str):
                    return result
                if isinstance(result, dict):
                    return result.get("answer") or result.get("text") or str(result)
        # Fallback: return last successful step output as string
        for step in reversed(plan.steps):
            if step.status == StepStatus.COMPLETED:
                result = context.get(step.id)
                return str(result) if result is not None else None
        return None
