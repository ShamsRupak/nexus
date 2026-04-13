"""REST API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nexus.core.executor import ApprovalRequiredError, PlanExecutor
from nexus.core.intent import IntentClassifier
from nexus.core.planner import PlanDecomposer
from nexus.core.types import AgentResponse, Plan

router = APIRouter()


class PromptRequest(BaseModel):
    prompt: str
    session_id: str | None = None


class ApproveRequest(BaseModel):
    plan_id: str


_classifier = IntentClassifier()
_planner = PlanDecomposer()
_executor = PlanExecutor()

# In-memory plan store (replace with DB in production)
_pending_plans: dict[str, Plan] = {}


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@router.post("/run", response_model=AgentResponse)
async def run_prompt(req: PromptRequest) -> AgentResponse:
    intent = await _classifier.classify(req.prompt)
    plan = await _planner.decompose(intent)

    try:
        return await _executor.execute(plan)
    except ApprovalRequiredError as e:
        _pending_plans[e.plan.id] = e.plan
        raise HTTPException(
            status_code=202,
            detail={
                "message": "Plan requires human approval",
                "plan_id": e.plan.id,
                "steps": [s.model_dump() for s in e.plan.steps],
            },
        )


@router.post("/approve", response_model=AgentResponse)
async def approve_plan(req: ApproveRequest) -> AgentResponse:
    plan = _pending_plans.pop(req.plan_id, None)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found or already executed")
    return await _executor.approve_and_execute(plan)


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str) -> dict:
    plan = _pending_plans.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan.model_dump()
