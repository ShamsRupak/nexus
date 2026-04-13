"""Tests for the plan decomposer (10+ tests)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

from nexus.core.planner import PlanDecomposer
from nexus.core.types import (
    ClassifiedIntent,
    IntentType,
    Plan,
    RiskLevel,
    Step,
    StepStatus,
)


@pytest.fixture
def planner():
    return PlanDecomposer()


def make_intent(
    intent_type: IntentType,
    prompt: str = "test prompt",
    risk: RiskLevel = RiskLevel.LOW,
) -> ClassifiedIntent:
    return ClassifiedIntent(
        intent_type=intent_type,
        confidence=0.9,
        entities=[],
        data_sources=["database"],
        risk_level=risk,
        original_prompt=prompt,
    )


# --------------------------------------------------------------------------
# Plan generation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_generates_plan(planner):
    intent = make_intent(IntentType.QUERY, "show me all deals")
    plan = await planner.decompose(intent)
    assert isinstance(plan, Plan)
    assert len(plan.steps) >= 1


@pytest.mark.asyncio
async def test_workflow_generates_multi_step_plan(planner):
    intent = make_intent(IntentType.WORKFLOW, "onboard new enterprise customer Acme")
    plan = await planner.decompose(intent)
    assert len(plan.steps) >= 2


@pytest.mark.asyncio
async def test_analysis_generates_multi_step_plan(planner):
    intent = make_intent(IntentType.ANALYSIS, "analyze revenue trends")
    plan = await planner.decompose(intent)
    assert len(plan.steps) >= 2


@pytest.mark.asyncio
async def test_action_requires_approval(planner):
    intent = make_intent(IntentType.ACTION, "create a customer record")
    plan = await planner.decompose(intent)
    assert plan.requires_approval is True


@pytest.mark.asyncio
async def test_workflow_requires_approval(planner):
    intent = make_intent(IntentType.WORKFLOW, "migrate all data to new schema")
    plan = await planner.decompose(intent)
    assert plan.requires_approval is True


@pytest.mark.asyncio
async def test_query_does_not_require_approval(planner):
    intent = make_intent(IntentType.QUERY, "show me all customers")
    plan = await planner.decompose(intent)
    assert plan.requires_approval is False


@pytest.mark.asyncio
async def test_high_risk_query_requires_approval(planner):
    """Even a QUERY is flagged for approval if risk level is HIGH."""
    intent = make_intent(IntentType.QUERY, "show me all data", risk=RiskLevel.HIGH)
    plan = await planner.decompose(intent)
    assert plan.requires_approval is True


@pytest.mark.asyncio
async def test_plan_ids_are_unique(planner):
    intent = make_intent(IntentType.QUERY)
    plan1 = await planner.decompose(intent)
    plan2 = await planner.decompose(intent)
    assert plan1.id != plan2.id


@pytest.mark.asyncio
async def test_trace_ids_are_generated(planner):
    intent = make_intent(IntentType.QUERY)
    plan = await planner.decompose(intent)
    assert plan.trace_id
    assert len(plan.trace_id) > 0


@pytest.mark.asyncio
async def test_all_steps_start_pending(planner):
    intent = make_intent(IntentType.ANALYSIS)
    plan = await planner.decompose(intent)
    for step in plan.steps:
        assert step.status == StepStatus.PENDING


# --------------------------------------------------------------------------
# DAG validation
# --------------------------------------------------------------------------


def test_validate_dag_no_cycle(planner):
    steps = [
        Step(id="s1", description="a", tool="postgres", depends_on=[]),
        Step(id="s2", description="b", tool="postgres", depends_on=["s1"]),
        Step(id="s3", description="c", tool="llm_synthesize", depends_on=["s2"]),
    ]
    assert planner._validate_dag(steps) is True


def test_validate_dag_detects_cycle(planner):
    steps = [
        Step(id="s1", description="a", tool="postgres", depends_on=["s3"]),
        Step(id="s2", description="b", tool="postgres", depends_on=["s1"]),
        Step(id="s3", description="c", tool="llm_synthesize", depends_on=["s2"]),
    ]
    assert planner._validate_dag(steps) is False


def test_validate_dag_detects_unknown_dependency(planner):
    steps = [
        Step(id="s1", description="a", tool="postgres", depends_on=["s99"]),
    ]
    assert planner._validate_dag(steps) is False


def test_topological_sort_respects_order(planner):
    steps = [
        Step(id="s3", description="c", tool="llm_synthesize", depends_on=["s1", "s2"]),
        Step(id="s1", description="a", tool="postgres", depends_on=[]),
        Step(id="s2", description="b", tool="vector_store", depends_on=[]),
    ]
    sorted_steps = planner._topological_sort(steps)
    ids = [s.id for s in sorted_steps]
    # s3 must come after s1 and s2
    assert ids.index("s3") > ids.index("s1")
    assert ids.index("s3") > ids.index("s2")


def test_topological_sort_linear_chain(planner):
    steps = [
        Step(id="s2", description="b", tool="postgres", depends_on=["s1"]),
        Step(id="s3", description="c", tool="llm_synthesize", depends_on=["s2"]),
        Step(id="s1", description="a", tool="postgres", depends_on=[]),
    ]
    sorted_steps = planner._topological_sort(steps)
    ids = [s.id for s in sorted_steps]
    assert ids == ["s1", "s2", "s3"]
