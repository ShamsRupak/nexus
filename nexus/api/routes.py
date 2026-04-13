"""REST API endpoints — full CRUD for prompts, plans, audit, and eval."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from nexus.core.executor import ApprovalRequiredError, PlanExecutor
from nexus.core.intent import IntentClassifier
from nexus.core.planner import PlanDecomposer
from nexus.core.types import AgentResponse, IntentType, Plan
from nexus.observe.audit import AuditStore, get_audit_store

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level singletons (reinitialised by tests via override helpers)
# ---------------------------------------------------------------------------

_classifier = IntentClassifier()
_planner = PlanDecomposer()
_executor = PlanExecutor()

# Plan storage: pending + recently completed
_pending_plans: dict[str, Plan] = {}
_recent_plans: list[dict[str, Any]] = []   # last 100 entries
_MAX_RECENT = 100

_audit = get_audit_store()


def get_plan_store() -> dict[str, Plan]:
    return _pending_plans


def get_audit_store_ref() -> AuditStore:
    return _audit


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class PromptRequest(BaseModel):
    prompt: str
    user_id: str | None = None


class ApproveRequest(BaseModel):
    plan_id: str


class PromptResponse(BaseModel):
    status: str  # "completed" | "awaiting_approval"
    plan_id: str
    result: AgentResponse | None = None
    steps: list[dict] | None = None   # returned when awaiting_approval
    message: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store_recent(plan: Plan, status: str, response: AgentResponse | None = None) -> None:
    global _recent_plans
    entry: dict[str, Any] = {
        "plan_id": plan.id,
        "prompt": plan.prompt[:200],
        "intent": plan.intent.value,
        "status": status,
        "requires_approval": plan.requires_approval,
        "trace_id": plan.trace_id,
        "created_at": plan.created_at.isoformat(),
        "step_count": len(plan.steps),
    }
    if response:
        entry["latency_ms"] = response.latency_ms
    _recent_plans = ([entry] + _recent_plans)[:_MAX_RECENT]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": "0.1.0",
        "components": {
            "classifier": "ok",
            "planner": "ok",
            "executor": "ok",
            "audit": "ok",
        },
    }


@router.post("/prompt", response_model=PromptResponse)
async def run_prompt(req: PromptRequest) -> PromptResponse:
    """Submit a prompt for execution."""
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt must not be empty")

    start = time.monotonic()
    intent = await _classifier.classify(req.prompt)
    plan = await _planner.decompose(intent)

    try:
        response = await _executor.execute(plan)
        latency_ms = (time.monotonic() - start) * 1000

        _audit.record(
            trace_id=plan.trace_id,
            action_type=intent.intent_type.value,
            connector="nexus",
            input_text=req.prompt,
            output_text=response.answer or "",
            approval_status="auto_approved",
            risk_level=intent.risk_level.value,
            duration_ms=round(latency_ms, 2),
            user_id=req.user_id,
        )
        _store_recent(plan, "completed", response)

        return PromptResponse(status="completed", plan_id=plan.id, result=response)

    except ApprovalRequiredError as exc:
        _pending_plans[exc.plan.id] = exc.plan
        _store_recent(plan, "awaiting_approval")

        _audit.record(
            trace_id=plan.trace_id,
            action_type=intent.intent_type.value,
            connector="nexus",
            input_text=req.prompt,
            output_text="",
            approval_status="pending",
            risk_level=intent.risk_level.value,
            duration_ms=0.0,
            user_id=req.user_id,
        )

        return PromptResponse(
            status="awaiting_approval",
            plan_id=plan.id,
            steps=[s.model_dump() for s in plan.steps],
            message="This plan requires human approval before execution.",
        )


@router.post("/approve/{plan_id}", response_model=PromptResponse)
async def approve_plan(plan_id: str) -> PromptResponse:
    """Approve a pending plan and execute it."""
    plan = _pending_plans.pop(plan_id, None)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found or already executed")

    start = time.monotonic()
    response = await _executor.approve_and_execute(plan)
    latency_ms = (time.monotonic() - start) * 1000

    _audit.record(
        trace_id=plan.trace_id,
        action_type=plan.intent.value,
        connector="nexus",
        input_text=plan.prompt,
        output_text=response.answer or "",
        approval_status="human_approved",
        risk_level="medium",
        duration_ms=round(latency_ms, 2),
    )
    _store_recent(plan, "completed", response)

    return PromptResponse(status="completed", plan_id=plan.id, result=response)


@router.get("/plans")
async def list_plans(limit: int = Query(default=20, le=100)) -> list[dict]:
    """List recent plans with status."""
    return _recent_plans[:limit]


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str) -> dict:
    """Get detailed plan info including step execution timeline."""
    plan = _pending_plans.get(plan_id)
    if plan:
        d = plan.model_dump()
        d["status"] = "awaiting_approval"
        return d

    entry = next((p for p in _recent_plans if p["plan_id"] == plan_id), None)
    if entry:
        return entry

    raise HTTPException(status_code=404, detail="Plan not found")


@router.get("/audit")
async def query_audit(
    trace_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    action_type: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, le=500),
) -> list[dict]:
    entries = _audit.query_audit(
        trace_id=trace_id,
        user_id=user_id,
        action_type=action_type,
        since=since,
        until=until,
        limit=limit,
    )
    return [e.model_dump() for e in entries]


@router.get("/audit/export")
async def export_audit(fmt: str = Query(default="json")) -> dict:
    """Export the full audit trail as JSON or CSV."""
    if fmt not in ("json", "csv"):
        raise HTTPException(status_code=422, detail="fmt must be 'json' or 'csv'")
    content = _audit.export_audit(fmt=fmt)
    return {"format": fmt, "content": content, "entry_count": _audit.count()}


@router.get("/connectors")
async def list_connectors() -> list[dict]:
    """Return registered connectors and their capabilities."""
    from nexus.connect.registry import get_registry
    return get_registry().list_connectors()


@router.get("/eval/report")
async def eval_report() -> dict:
    """Run the built-in regression suite and return the report."""
    from nexus.eval.regression import RegressionRunner

    runner = RegressionRunner()
    runner.add_case(
        "query_deals",
        "show me all deals",
        {"intent": IntentType.QUERY.value, "requires_approval": False},
    )
    runner.add_case(
        "action_create",
        "create a new customer record",
        {"intent": IntentType.ACTION.value, "requires_approval": True},
    )
    runner.add_case(
        "analysis_revenue",
        "analyze revenue trends",
        {"intent": IntentType.ANALYSIS.value, "requires_approval": False},
    )

    report = await runner.run_all()
    return {
        "run_id": report.run_id,
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "pass_rate": report.pass_rate,
        "results": [r.model_dump() for r in report.results],
    }
