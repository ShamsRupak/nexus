"""Multi-source context assembler."""

from __future__ import annotations

from typing import Any


class ContextAssembler:
    """Assembles context from multiple data sources for step execution."""

    async def assemble(
        self,
        step_id: str,
        prior_results: dict[str, Any],
        data_sources: list[str],
    ) -> dict[str, Any]:
        context: dict[str, Any] = {}
        context["prior_results"] = prior_results
        context["data_sources"] = data_sources
        return context
