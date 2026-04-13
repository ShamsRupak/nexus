"""Shared types for the Nexus agent orchestration platform."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class IntentType(StrEnum):
    QUERY = "query"  # Read-only data retrieval
    ACTION = "action"  # Mutating operation (create, update, delete)
    ANALYSIS = "analysis"  # Data analysis + insight generation
    WORKFLOW = "workflow"  # Multi-step automated process


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"


class ClassifiedIntent(BaseModel):
    """Output of the intent classifier."""

    intent_type: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    original_prompt: str
    reasoning: str = ""


class Step(BaseModel):
    """A single executable step within a plan."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Any | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds() * 1000
        return None


class Plan(BaseModel):
    """A DAG-structured execution plan derived from a user prompt."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str
    intent: IntentType
    steps: list[Step] = Field(default_factory=list)
    requires_approval: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    def get_step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)


class AgentResponse(BaseModel):
    """Final response returned from a completed plan execution."""

    plan_id: str
    answer: str | None = None
    data: dict[str, Any] | None = None
    actions_taken: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str
    latency_ms: float
    token_usage: dict[str, int] = Field(default_factory=dict)


class StepResult(BaseModel):
    """Result from executing a single step."""

    step_id: str
    success: bool
    output: Any = None
    error: str | None = None
    token_usage: dict[str, int] = Field(default_factory=dict)
