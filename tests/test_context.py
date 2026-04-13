"""Tests for the context manager — 10+ tests."""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

from nexus.connect.registry import BaseConnector, ConnectorRegistry
from nexus.core.context import ContextManager, StepContext
from nexus.core.types import IntentType, Plan, Step, StepStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_plan(*steps: Step) -> Plan:
    return Plan(
        prompt="test",
        intent=IntentType.QUERY,
        steps=list(steps),
    )


def make_step(
    step_id: str,
    tool: str = "postgres",
    depends_on: list[str] | None = None,
    params: dict | None = None,
    result: Any = None,
    status: StepStatus = StepStatus.PENDING,
) -> Step:
    s = Step(
        id=step_id,
        description=f"Step {step_id}",
        tool=tool,
        depends_on=depends_on or [],
        params=params or {},
        status=status,
    )
    s.result = result
    return s


class _MockConnector(BaseConnector):
    """Configurable mock connector for context tests."""

    def __init__(self, name: str, response: dict | None = None) -> None:
        self.name = name
        self.description = f"Mock {name}"
        self._response = response or {"success": True, "data": [{"col": "val"}]}
        self.call_count = 0

    def get_capabilities(self) -> list[str]:
        return ["nl_query", "search"]

    async def health_check(self) -> bool:
        return True

    async def execute(self, action: str, params: dict) -> dict:
        self.call_count += 1
        return self._response


def make_registry(*connectors: _MockConnector) -> ConnectorRegistry:
    reg = ConnectorRegistry()
    for c in connectors:
        reg.register(c)
    return reg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_assembly_basic():
    """A step with no deps and no connector queries should return empty context."""
    step = make_step("s1", tool="postgres")
    plan = make_plan(step)
    ctx_mgr = ContextManager()
    ctx = await ctx_mgr.assemble(step, plan)
    assert isinstance(ctx, StepContext)
    assert ctx.step_id == "s1"


@pytest.mark.asyncio
async def test_context_dependency_results_included():
    """Completed dependency step results should appear in context."""
    s1 = make_step("s1", result={"rows": [{"id": 1}]}, status=StepStatus.COMPLETED)
    s2 = make_step("s2", depends_on=["s1"])
    plan = make_plan(s1, s2)

    ctx_mgr = ContextManager()
    ctx = await ctx_mgr.assemble(s2, plan)

    assert "s1" in ctx.dependency_results
    assert ctx.dependency_results["s1"] == {"rows": [{"id": 1}]}


@pytest.mark.asyncio
async def test_context_no_deps_returns_empty_dependency_results():
    step = make_step("s1")
    plan = make_plan(step)
    ctx_mgr = ContextManager()
    ctx = await ctx_mgr.assemble(step, plan)
    assert ctx.dependency_results == {}


@pytest.mark.asyncio
async def test_context_queries_connector_for_nl_query():
    """Step with nl_query param should trigger connector.execute()."""
    mock_pg = _MockConnector("postgres", response={"success": True, "data": [{"deal": "A"}]})
    reg = make_registry(mock_pg)

    step = make_step("s1", tool="postgres", params={"nl_query": "show all deals"})
    plan = make_plan(step)

    ctx_mgr = ContextManager()
    ctx = await ctx_mgr.assemble(step, plan, connectors=reg)

    assert mock_pg.call_count == 1
    assert ctx.data == [{"deal": "A"}]


@pytest.mark.asyncio
async def test_context_queries_vector_store_for_rag():
    """Step with rag_query param should call vector_store connector."""
    mock_vs = _MockConnector(
        "vector_store",
        response={"success": True, "results": [{"content": "refund policy text", "score": 0.9}]},
    )
    reg = make_registry(mock_vs)

    step = make_step("s1", tool="vector_store", params={"rag_query": "what is the refund policy"})
    plan = make_plan(step)

    ctx_mgr = ContextManager()
    ctx = await ctx_mgr.assemble(step, plan, connectors=reg)

    assert mock_vs.call_count == 1
    assert len(ctx.rag_chunks) == 1
    assert ctx.rag_chunks[0]["score"] == 0.9


@pytest.mark.asyncio
async def test_context_merges_rag_and_data():
    """Steps can request both db data and rag chunks simultaneously."""
    mock_pg = _MockConnector("postgres", response={"success": True, "data": [{"id": 1}]})
    mock_vs = _MockConnector(
        "vector_store",
        response={"success": True, "results": [{"content": "chunk", "score": 0.8}]},
    )
    reg = make_registry(mock_pg, mock_vs)

    step = make_step(
        "s1",
        params={"nl_query": "show deals", "rag_query": "deal policies"},
    )
    plan = make_plan(step)

    ctx_mgr = ContextManager()
    ctx = await ctx_mgr.assemble(step, plan, connectors=reg)

    assert len(ctx.data) >= 1
    assert len(ctx.rag_chunks) >= 1


@pytest.mark.asyncio
async def test_context_no_connector_still_assembles():
    """Assembly should succeed even when no connectors are provided."""
    step = make_step("s1", params={"nl_query": "show deals"})
    plan = make_plan(step)
    ctx_mgr = ContextManager()
    ctx = await ctx_mgr.assemble(step, plan, connectors=None)
    assert ctx.data == []


@pytest.mark.asyncio
async def test_context_conversation_history_included():
    history = [
        {"role": "user", "content": "show deals"},
        {"role": "assistant", "content": "Here are 5 deals"},
    ]
    ctx_mgr = ContextManager(conversation_history=history)
    step = make_step("s1")
    plan = make_plan(step)
    ctx = await ctx_mgr.assemble(step, plan)
    assert len(ctx.conversation_history) == 2


@pytest.mark.asyncio
async def test_context_conversation_history_capped_at_6():
    """Only last 6 history entries are included (3 turns)."""
    history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    ctx_mgr = ContextManager(conversation_history=history)
    step = make_step("s1")
    plan = make_plan(step)
    ctx = await ctx_mgr.assemble(step, plan)
    assert len(ctx.conversation_history) <= 6


def test_token_estimation_nonzero():
    ctx_mgr = ContextManager()
    data = {"dependency_results": {"s1": {"rows": list(range(100))}}, "data": [], "rag_chunks": []}
    tokens = ctx_mgr._estimate_tokens(data)
    assert tokens > 0


def test_token_estimation_grows_with_content():
    ctx_mgr = ContextManager()
    small = {"data": [{"id": 1}]}
    large = {"data": [{"id": i, "desc": "word " * 50} for i in range(20)]}
    assert ctx_mgr._estimate_tokens(large) > ctx_mgr._estimate_tokens(small)


def test_context_truncation_reduces_tokens():
    ctx_mgr = ContextManager(max_tokens=100)
    big_ctx = {
        "dependency_results": {},
        "data": [{"id": i, "description": "filler " * 20} for i in range(50)],
        "rag_chunks": [{"content": "chunk " * 20, "score": 0.5} for _ in range(10)],
        "conversation_history": [{"role": "user", "content": "hello " * 20} for _ in range(10)],
    }
    before = ctx_mgr._estimate_tokens(big_ctx)
    truncated = ctx_mgr._truncate_context(big_ctx, max_tokens=100)
    after = ctx_mgr._estimate_tokens(truncated)
    assert after < before


def test_context_truncation_preserves_dependency_results():
    """Dependency results must never be truncated — they carry step outputs."""
    ctx_mgr = ContextManager()
    ctx = {
        "dependency_results": {"s1": {"critical": "data"}},
        "data": [{"id": i} for i in range(100)],
        "rag_chunks": [],
        "conversation_history": [],
    }
    truncated = ctx_mgr._truncate_context(ctx, max_tokens=50)
    # Dependency results must survive
    assert "s1" in truncated["dependency_results"]
    assert truncated["dependency_results"]["s1"] == {"critical": "data"}


def test_context_add_to_history():
    ctx_mgr = ContextManager()
    ctx_mgr.add_to_history("user", "show deals")
    ctx_mgr.add_to_history("assistant", "Here are 5 deals")
    assert len(ctx_mgr._history) == 2
    assert ctx_mgr._history[0]["role"] == "user"
