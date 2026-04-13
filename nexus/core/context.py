"""Context manager — assembles multi-source context for each plan step."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from nexus.core.types import Plan, Step

logger = logging.getLogger(__name__)

_MAX_CONTEXT_TOKENS = 6000
_CHARS_PER_TOKEN = 4  # approximation; replaced by tiktoken when available


@dataclass
class StepContext:
    """All context available to a step at execution time."""

    step_id: str
    dependency_results: dict[str, Any] = field(default_factory=dict)
    data: list[dict] = field(default_factory=list)
    rag_chunks: list[dict] = field(default_factory=list)
    conversation_history: list[dict] = field(default_factory=list)
    token_estimate: int = 0
    truncated: bool = False


class ContextManager:
    """Assembles step context from connector results, prior steps, and conversation history."""

    def __init__(
        self,
        max_tokens: int = _MAX_CONTEXT_TOKENS,
        conversation_history: list[dict] | None = None,
    ) -> None:
        self._max_tokens = max_tokens
        self._history = conversation_history or []

    async def assemble(
        self,
        step: Step,
        plan: Plan,
        connectors: Any | None = None,  # ConnectorRegistry
    ) -> StepContext:
        """Build a StepContext for the given step within its plan."""

        # 1. Pull results from dependency steps
        dep_results: dict[str, Any] = {}
        for dep_id in step.depends_on:
            dep_step = plan.get_step(dep_id)
            if dep_step and dep_step.result is not None:
                dep_results[dep_id] = dep_step.result

        # 2. Optionally query a data connector for fresh records
        data: list[dict] = []
        if connectors and step.params.get("nl_query"):
            conn = connectors.get(step.tool) or connectors.get("postgres")
            if conn:
                try:
                    result = await conn.execute("nl_query", {"query": step.params["nl_query"]})
                    data = result.get("data", [])
                except Exception as exc:
                    logger.warning("Connector query failed for step %s: %s", step.id, exc)

        # 3. Optionally run RAG search against vector store
        rag_chunks: list[dict] = []
        if connectors and step.params.get("rag_query"):
            vs = connectors.get("vector_store")
            if vs:
                try:
                    result = await vs.execute(
                        "search",
                        {
                            "query": step.params["rag_query"],
                            "collection": step.params.get("rag_collection", "default"),
                            "top_k": step.params.get("rag_top_k", 5),
                        },
                    )
                    rag_chunks = result.get("results", [])
                except Exception as exc:
                    logger.warning("RAG search failed for step %s: %s", step.id, exc)

        # 4. Assemble raw context dict and estimate tokens
        raw: dict[str, Any] = {
            "dependency_results": dep_results,
            "data": data,
            "rag_chunks": rag_chunks,
            "conversation_history": self._history[-6:],  # last 3 turns
        }

        token_est = self._estimate_tokens(raw)
        truncated = False

        if token_est > self._max_tokens:
            raw = self._truncate_context(raw, self._max_tokens)
            token_est = self._estimate_tokens(raw)
            truncated = True
            logger.info("Context for step %s truncated to ~%d tokens", step.id, token_est)

        return StepContext(
            step_id=step.id,
            dependency_results=raw["dependency_results"],
            data=raw["data"],
            rag_chunks=raw["rag_chunks"],
            conversation_history=raw["conversation_history"],
            token_estimate=token_est,
            truncated=truncated,
        )

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _estimate_tokens(self, context: dict) -> int:
        """Estimate token count from serialised context size."""
        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
            text = str(context)
            return len(enc.encode(text))
        except Exception:
            return len(str(context)) // _CHARS_PER_TOKEN

    def _truncate_context(self, context: dict, max_tokens: int) -> dict:
        """Trim context to fit within the token budget.

        Strategy: preserve dependency_results and recent rag_chunks;
        trim data rows and conversation history first.
        """
        # Work on copies
        ctx = dict(context)
        ctx["data"] = list(context.get("data", []))
        ctx["rag_chunks"] = list(context.get("rag_chunks", []))
        ctx["conversation_history"] = list(context.get("conversation_history", []))

        # First: trim conversation history (oldest first)
        while self._estimate_tokens(ctx) > max_tokens and ctx["conversation_history"]:
            ctx["conversation_history"].pop(0)

        # Second: trim data rows (keep first N)
        while self._estimate_tokens(ctx) > max_tokens and len(ctx["data"]) > 1:
            ctx["data"] = ctx["data"][: max(1, len(ctx["data"]) // 2)]

        # Third: trim rag chunks (least relevant last)
        while self._estimate_tokens(ctx) > max_tokens and len(ctx["rag_chunks"]) > 1:
            ctx["rag_chunks"].pop()

        return ctx

    def add_to_history(self, role: str, content: str) -> None:
        self._history.append({"role": role, "content": content})
