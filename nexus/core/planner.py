"""DAG-based plan decomposer — converts classified intents into executable plans."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict, deque

from nexus.config import get_settings
from nexus.core.types import (
    ClassifiedIntent,
    IntentType,
    Plan,
    RiskLevel,
    Step,
    StepStatus,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a plan decomposer for an enterprise AI agent platform.
Given a classified intent, decompose it into 1-8 concrete execution steps.

Each step must have:
- id: short unique string (e.g. "s1", "s2")
- description: what the step does
- tool: one of "postgres", "vector_store", "rest_api", "file_ingest", "llm_synthesize"
- params: dict of parameters for the tool
- depends_on: list of step IDs this step requires to complete first

Rules:
1. steps must form a valid DAG (no circular dependencies)
2. "llm_synthesize" is always the final step that assembles the answer
3. data retrieval steps run before synthesis
4. ACTION and WORKFLOW intents need a "validate" step before any mutating step
5. Keep it minimal — don't create steps that aren't needed

Respond ONLY with a JSON array of steps. No markdown, no explanation.

Example for "show me Q4 deals over $50k":
[
  {"id": "s1", "description": "Query deals database for Q4 deals", "tool": "postgres",
   "params": {"query": "SELECT * FROM deals WHERE quarter='Q4' AND amount > 50000"},
   "depends_on": []},
  {"id": "s2", "description": "Synthesize response from query results", "tool": "llm_synthesize",
   "params": {"prompt_template": "Summarise these deals: {s1}"},
   "depends_on": ["s1"]}
]
"""

# Fallback single-step templates per intent type
_FALLBACK_STEPS: dict[IntentType, list[dict]] = {
    IntentType.QUERY: [
        {
            "id": "s1",
            "description": "Retrieve requested data",
            "tool": "postgres",
            "params": {},
            "depends_on": [],
        },
        {
            "id": "s2",
            "description": "Synthesize natural language response",
            "tool": "llm_synthesize",
            "params": {"prompt_template": "Answer the question based on: {s1}"},
            "depends_on": ["s1"],
        },
    ],
    IntentType.ACTION: [
        {
            "id": "s1",
            "description": "Validate input parameters",
            "tool": "postgres",
            "params": {"validate": True},
            "depends_on": [],
        },
        {
            "id": "s2",
            "description": "Execute the action",
            "tool": "postgres",
            "params": {},
            "depends_on": ["s1"],
        },
        {
            "id": "s3",
            "description": "Confirm action completed",
            "tool": "llm_synthesize",
            "params": {"prompt_template": "Confirm this action: {s2}"},
            "depends_on": ["s2"],
        },
    ],
    IntentType.ANALYSIS: [
        {
            "id": "s1",
            "description": "Retrieve data for analysis",
            "tool": "postgres",
            "params": {},
            "depends_on": [],
        },
        {
            "id": "s2",
            "description": "Fetch relevant documents",
            "tool": "vector_store",
            "params": {},
            "depends_on": [],
        },
        {
            "id": "s3",
            "description": "Synthesize analysis and insights",
            "tool": "llm_synthesize",
            "params": {"prompt_template": "Analyse this data: {s1} {s2}"},
            "depends_on": ["s1", "s2"],
        },
    ],
    IntentType.WORKFLOW: [
        {
            "id": "s1",
            "description": "Gather required information",
            "tool": "postgres",
            "params": {},
            "depends_on": [],
        },
        {
            "id": "s2",
            "description": "Search knowledge base for procedures",
            "tool": "vector_store",
            "params": {},
            "depends_on": [],
        },
        {
            "id": "s3",
            "description": "Execute workflow steps",
            "tool": "rest_api",
            "params": {},
            "depends_on": ["s1", "s2"],
        },
        {
            "id": "s4",
            "description": "Summarise workflow execution",
            "tool": "llm_synthesize",
            "params": {"prompt_template": "Summarise workflow: {s3}"},
            "depends_on": ["s3"],
        },
    ],
}


class PlanDecomposer:
    """Converts a ClassifiedIntent into a DAG-structured Plan."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(
                    api_key=self._settings.openai_api_key,
                    base_url=self._settings.openai_base_url,
                )
            except Exception as exc:
                logger.warning("Could not initialise OpenAI client: %s", exc)
        return self._client

    async def decompose(self, intent: ClassifiedIntent) -> Plan:
        """Decompose a classified intent into an executable Plan."""
        requires_approval = intent.intent_type in (IntentType.ACTION, IntentType.WORKFLOW) or (
            intent.risk_level == RiskLevel.HIGH
        )

        if self._settings.llm_available:
            try:
                steps = await self._llm_decompose(intent)
                if steps and self._validate_dag(steps):
                    return self._build_plan(intent, steps, requires_approval)
                logger.warning("LLM produced invalid DAG, falling back to template")
            except Exception as exc:
                logger.warning("LLM decomposition failed, using template: %s", exc)

        steps = self._template_steps(intent)
        return self._build_plan(intent, steps, requires_approval)

    async def _llm_decompose(self, intent: ClassifiedIntent) -> list[Step]:
        client = self._get_client()
        if client is None:
            return []

        context = {
            "prompt": intent.original_prompt,
            "intent_type": intent.intent_type.value,
            "entities": intent.entities,
            "data_sources": intent.data_sources,
            "risk_level": intent.risk_level.value,
        }

        response = await client.chat.completions.create(
            model=self._settings.llm_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context)},
            ],
            temperature=0.1,
            max_tokens=1024,
        )

        raw = response.choices[0].message.content or "[]"
        # Strip potential markdown fences
        raw = raw.strip().strip("```json").strip("```").strip()
        step_dicts = json.loads(raw)

        return [
            Step(
                id=d["id"],
                description=d["description"],
                tool=d["tool"],
                params=d.get("params", {}),
                depends_on=d.get("depends_on", []),
                status=StepStatus.PENDING,
            )
            for d in step_dicts
        ]

    def _template_steps(self, intent: ClassifiedIntent) -> list[Step]:
        templates = _FALLBACK_STEPS.get(intent.intent_type, _FALLBACK_STEPS[IntentType.QUERY])
        return [
            Step(
                id=t["id"],
                description=t["description"],
                tool=t["tool"],
                params=dict(t["params"]),
                depends_on=list(t["depends_on"]),
                status=StepStatus.PENDING,
            )
            for t in templates
        ]

    def _build_plan(
        self,
        intent: ClassifiedIntent,
        steps: list[Step],
        requires_approval: bool,
    ) -> Plan:
        sorted_steps = self._topological_sort(steps)
        return Plan(
            id=str(uuid.uuid4()),
            prompt=intent.original_prompt,
            intent=intent.intent_type,
            steps=sorted_steps,
            requires_approval=requires_approval,
            trace_id=str(uuid.uuid4()),
        )

    def _validate_dag(self, steps: list[Step]) -> bool:
        """Return True if steps form a valid DAG (no cycles, all deps exist)."""
        step_ids = {s.id for s in steps}

        # Ensure all declared dependencies exist
        for step in steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    logger.warning("Step %s depends on unknown step %s", step.id, dep)
                    return False

        # Detect cycles via DFS
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {s.id: WHITE for s in steps}
        adj: dict[str, list[str]] = {s.id: list(s.depends_on) for s in steps}

        def dfs(node: str) -> bool:
            color[node] = GRAY
            for neighbour in adj[node]:
                if color[neighbour] == GRAY:
                    return True  # cycle
                if color[neighbour] == WHITE and dfs(neighbour):
                    return True
            color[node] = BLACK
            return False

        for step in steps:
            if color[step.id] == WHITE:
                if dfs(step.id):
                    return False  # cycle detected

        return True

    def _topological_sort(self, steps: list[Step]) -> list[Step]:
        """Kahn's algorithm — returns steps in safe execution order."""
        in_degree: dict[str, int] = defaultdict(int)
        dependents: dict[str, list[str]] = defaultdict(list)
        step_map = {s.id: s for s in steps}

        for step in steps:
            in_degree.setdefault(step.id, 0)
            for dep in step.depends_on:
                in_degree[step.id] += 1
                dependents[dep].append(step.id)

        queue: deque[str] = deque(sid for sid, deg in in_degree.items() if deg == 0)
        sorted_ids: list[str] = []

        while queue:
            sid = queue.popleft()
            sorted_ids.append(sid)
            for child in dependents[sid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(sorted_ids) != len(steps):
            # Cycle exists — return original order as fallback
            logger.error("Cycle detected during topological sort, returning original order")
            return steps

        return [step_map[sid] for sid in sorted_ids]
