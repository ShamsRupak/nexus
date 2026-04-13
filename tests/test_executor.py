"""Tests for the plan execution engine (5+ tests)."""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

from nexus.core.executor import ApprovalRequiredError, PlanExecutor
from nexus.core.types import (
    IntentType,
    Plan,
    Step,
    StepStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_plan(
    steps: list[Step],
    requires_approval: bool = False,
    intent: IntentType = IntentType.QUERY,
) -> Plan:
    return Plan(
        prompt="test prompt",
        intent=intent,
        steps=steps,
        requires_approval=requires_approval,
    )


async def stub_tool(step: Step, context: dict):
    """No-op tool that returns a fixed response."""
    return {"result": f"output_of_{step.id}"}


async def slow_tool(step: Step, context: dict):
    """Tool that sleeps longer than the timeout."""
    await asyncio.sleep(60)
    return {}


async def failing_tool(step: Step, context: dict):
    """Tool that always raises."""
    raise RuntimeError("Simulated tool failure")


def make_executor(tools: dict | None = None, timeout: int = 5) -> PlanExecutor:
    executor = PlanExecutor(tool_registry=tools or {})
    executor._settings.step_timeout_seconds = timeout
    executor._settings.max_retries = 1  # Fast tests — no retries
    return executor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_step_plan_executes_successfully():
    steps = [
        Step(id="s1", description="fetch data", tool="postgres", depends_on=[])
    ]
    plan = make_plan(steps)
    executor = make_executor({"postgres": stub_tool})

    response = await executor.execute(plan)

    assert response.plan_id == plan.id
    assert plan.steps[0].status == StepStatus.COMPLETED
    assert len(response.actions_taken) == 1
    assert response.actions_taken[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_multi_step_plan_respects_dependency_order():
    execution_order: list[str] = []

    async def ordered_tool(step: Step, context: dict):
        execution_order.append(step.id)
        return {"order": len(execution_order)}

    steps = [
        Step(id="s1", description="step 1", tool="t", depends_on=[]),
        Step(id="s2", description="step 2", tool="t", depends_on=["s1"]),
        Step(id="s3", description="step 3", tool="t", depends_on=["s2"]),
    ]
    plan = make_plan(steps)
    executor = make_executor({"t": ordered_tool})

    await executor.execute(plan)

    assert execution_order == ["s1", "s2", "s3"]


@pytest.mark.asyncio
async def test_failed_step_cascades_to_dependents():
    steps = [
        Step(id="s1", description="will fail", tool="bad", depends_on=[]),
        Step(id="s2", description="depends on s1", tool="good", depends_on=["s1"]),
    ]
    plan = make_plan(steps)
    executor = make_executor({"bad": failing_tool, "good": stub_tool})

    response = await executor.execute(plan)

    assert plan.steps[0].status == StepStatus.FAILED
    assert plan.steps[1].status == StepStatus.FAILED
    assert plan.steps[1].error == "Skipped — dependency failed"


@pytest.mark.asyncio
async def test_step_timeout_is_enforced():
    steps = [Step(id="s1", description="slow step", tool="slow", depends_on=[])]
    plan = make_plan(steps)
    executor = make_executor({"slow": slow_tool}, timeout=1)

    response = await executor.execute(plan)

    assert plan.steps[0].status == StepStatus.FAILED
    assert "timed out" in (plan.steps[0].error or "").lower()


@pytest.mark.asyncio
async def test_plan_with_requires_approval_pauses():
    steps = [Step(id="s1", description="mutating step", tool="postgres", depends_on=[])]
    plan = make_plan(steps, requires_approval=True, intent=IntentType.ACTION)
    executor = make_executor({"postgres": stub_tool})

    with pytest.raises(ApprovalRequiredError) as exc_info:
        await executor.execute(plan)

    assert exc_info.value.plan.id == plan.id
    # Steps should be marked awaiting approval
    assert plan.steps[0].status == StepStatus.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_approve_and_execute_runs_after_approval():
    steps = [Step(id="s1", description="action step", tool="postgres", depends_on=[])]
    plan = make_plan(steps, requires_approval=True, intent=IntentType.ACTION)
    executor = make_executor({"postgres": stub_tool})

    # First call should raise
    with pytest.raises(ApprovalRequiredError):
        await executor.execute(plan)

    # After approval, should execute successfully
    response = await executor.approve_and_execute(plan)
    assert plan.steps[0].status == StepStatus.COMPLETED
    assert response.plan_id == plan.id


@pytest.mark.asyncio
async def test_parallel_independent_steps_all_complete():
    """Steps with no dependencies between them should all complete."""
    steps = [
        Step(id="s1", description="fetch crm", tool="t", depends_on=[]),
        Step(id="s2", description="fetch docs", tool="t", depends_on=[]),
        Step(id="s3", description="synthesize", tool="t", depends_on=["s1", "s2"]),
    ]
    plan = make_plan(steps)
    executor = make_executor({"t": stub_tool})

    response = await executor.execute(plan)

    assert all(s.status == StepStatus.COMPLETED for s in plan.steps)
    assert len(response.actions_taken) == 3


@pytest.mark.asyncio
async def test_response_includes_trace_id():
    steps = [Step(id="s1", description="step", tool="t", depends_on=[])]
    plan = make_plan(steps)
    executor = make_executor({"t": stub_tool})

    response = await executor.execute(plan)

    assert response.trace_id == plan.trace_id
    assert response.latency_ms >= 0
