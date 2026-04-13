"""WebSocket streaming endpoint for real-time plan execution updates."""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from nexus.core.intent import IntentClassifier
from nexus.core.planner import PlanDecomposer
from nexus.core.types import StepStatus

ws_router = APIRouter()

_classifier = IntentClassifier()
_planner = PlanDecomposer()


@ws_router.websocket("/ws/run")
async def ws_run(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            prompt = payload.get("prompt", "")

            if not prompt:
                await websocket.send_json({"error": "Empty prompt"})
                continue

            await websocket.send_json({"event": "classifying"})
            intent = await _classifier.classify(prompt)
            await websocket.send_json(
                {"event": "intent_classified", "intent": intent.intent_type.value}
            )

            await websocket.send_json({"event": "planning"})
            plan = await _planner.decompose(intent)
            await websocket.send_json(
                {
                    "event": "plan_ready",
                    "plan_id": plan.id,
                    "steps": len(plan.steps),
                    "requires_approval": plan.requires_approval,
                }
            )

            if plan.requires_approval:
                await websocket.send_json(
                    {
                        "event": "awaiting_approval",
                        "plan_id": plan.id,
                        "message": "This plan requires human approval before execution",
                    }
                )
            else:
                from nexus.core.executor import PlanExecutor

                executor = PlanExecutor()
                response = await executor.execute(plan)
                await websocket.send_json(
                    {
                        "event": "completed",
                        "answer": response.answer,
                        "latency_ms": response.latency_ms,
                        "trace_id": response.trace_id,
                    }
                )

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"event": "error", "detail": str(exc)})
        except Exception:
            pass
