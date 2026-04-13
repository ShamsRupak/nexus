"""Intent classifier — categorizes user prompts and extracts metadata."""

from __future__ import annotations

import json
import logging
import re

from nexus.core.types import ClassifiedIntent, IntentType, RiskLevel
from nexus.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an intent classifier for an enterprise AI agent platform.
Given a user prompt, respond with a JSON object containing:
- intent_type: one of "query", "action", "analysis", "workflow"
- confidence: float 0.0-1.0
- entities: list of named entities (companies, people, dates, IDs)
- data_sources: list of data sources needed (e.g. "crm", "database", "documents", "api")
- risk_level: "low", "medium", or "high"
  - high = deletes, bulk updates, sends external communications, financial transactions
  - medium = single record create/update, sends internal notifications
  - low = read-only operations
- reasoning: one sentence explaining your classification

Definitions:
- query: read-only retrieval ("show", "list", "what", "who", "how many", "find", "get")
- action: mutating operation ("create", "update", "delete", "send", "approve", "cancel")
- analysis: insights + patterns ("analyze", "compare", "trend", "forecast", "summarize", "report")
- workflow: multi-step automated process ("onboard", "setup", "migrate", "process", "automate")

Respond ONLY with valid JSON. No markdown, no explanation outside JSON.
"""

# Keyword patterns for fallback classification
_QUERY_PATTERNS = re.compile(
    r"\b(show|list|what|who|how many|find|get|fetch|display|tell me|describe)\b",
    re.IGNORECASE,
)
_ACTION_PATTERNS = re.compile(
    r"\b(create|update|delete|remove|send|approve|cancel|modify|add|insert|edit|submit)\b",
    re.IGNORECASE,
)
_ANALYSIS_PATTERNS = re.compile(
    r"\b(analyze|analyse|compare|trend|forecast|summarize|summarise|report|insight|predict|chart)\b",
    re.IGNORECASE,
)
_WORKFLOW_PATTERNS = re.compile(
    r"\b(onboard|setup|set up|migrate|process|automate|workflow|pipeline|batch)\b",
    re.IGNORECASE,
)
_HIGH_RISK_PATTERNS = re.compile(
    r"\b(delete|remove|drop|purge|wipe|all records|bulk|mass|everyone|all users)\b",
    re.IGNORECASE,
)
_MEDIUM_RISK_PATTERNS = re.compile(
    r"\b(create|update|modify|edit|send|approve|cancel|submit)\b",
    re.IGNORECASE,
)


class IntentClassifier:
    """Classifies user prompts using LLM with keyword-based fallback."""

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

    async def classify(self, prompt: str) -> ClassifiedIntent:
        """Classify a user prompt, falling back to keyword heuristics if LLM unavailable."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty")

        prompt = prompt.strip()
        if len(prompt) > 8000:
            prompt = prompt[:8000]
            logger.warning("Prompt truncated to 8000 characters")

        if self._settings.llm_available:
            try:
                return await self._llm_classify(prompt)
            except Exception as exc:
                logger.warning("LLM classification failed, using keyword fallback: %s", exc)

        return self._keyword_fallback(prompt)

    async def _llm_classify(self, prompt: str) -> ClassifiedIntent:
        client = self._get_client()
        if client is None:
            return self._keyword_fallback(prompt)

        response = await client.chat.completions.create(
            model=self._settings.llm_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=512,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)

        return ClassifiedIntent(
            intent_type=IntentType(data.get("intent_type", "query")),
            confidence=float(data.get("confidence", 0.8)),
            entities=data.get("entities", []),
            data_sources=data.get("data_sources", []),
            risk_level=RiskLevel(data.get("risk_level", "low")),
            original_prompt=prompt,
            reasoning=data.get("reasoning", ""),
        )

    def _keyword_fallback(self, prompt: str) -> ClassifiedIntent:
        """Keyword-based classification used when LLM is unavailable."""
        scores: dict[IntentType, int] = {
            IntentType.QUERY: 0,
            IntentType.ACTION: 0,
            IntentType.ANALYSIS: 0,
            IntentType.WORKFLOW: 0,
        }

        if _QUERY_PATTERNS.search(prompt):
            scores[IntentType.QUERY] += 2
        if _ACTION_PATTERNS.search(prompt):
            scores[IntentType.ACTION] += 2
        if _ANALYSIS_PATTERNS.search(prompt):
            scores[IntentType.ANALYSIS] += 2
        if _WORKFLOW_PATTERNS.search(prompt):
            scores[IntentType.WORKFLOW] += 2

        # Tie-break: default to QUERY (safest)
        best = max(scores, key=lambda k: (scores[k], k == IntentType.QUERY))
        if scores[best] == 0:
            best = IntentType.QUERY

        # Risk level
        if _HIGH_RISK_PATTERNS.search(prompt):
            risk = RiskLevel.HIGH
        elif _MEDIUM_RISK_PATTERNS.search(prompt):
            risk = RiskLevel.MEDIUM
        else:
            risk = RiskLevel.LOW

        # Naive entity extraction: capitalised multi-word sequences
        entities = re.findall(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\b", prompt)
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_entities = [e for e in entities if not (e in seen or seen.add(e))]  # type: ignore[func-returns-value]

        total = sum(scores.values())
        confidence = (scores[best] / total) if total > 0 else 0.5

        return ClassifiedIntent(
            intent_type=best,
            confidence=round(confidence, 2),
            entities=unique_entities,
            data_sources=_infer_data_sources(prompt),
            risk_level=risk,
            original_prompt=prompt,
            reasoning=f"Keyword fallback: matched {best.value} pattern",
        )


def _infer_data_sources(prompt: str) -> list[str]:
    sources: list[str] = []
    lower = prompt.lower()
    if any(w in lower for w in ("deal", "customer", "crm", "lead", "opportunity")):
        sources.append("crm")
    if any(w in lower for w in ("database", "sql", "table", "record", "row")):
        sources.append("database")
    if any(w in lower for w in ("document", "pdf", "policy", "file", "doc")):
        sources.append("documents")
    if any(w in lower for w in ("api", "endpoint", "service", "integration")):
        sources.append("api")
    return sources or ["database"]
