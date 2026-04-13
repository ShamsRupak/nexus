"""WebSocket streaming — real-time plan execution events with connection manager."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from nexus.core.intent import IntentClassifier
from nexus.core.planner import PlanDecomposer
from nexus.observe.logger import get_logger

ws_router = APIRouter()
_log = get_logger("api.ws")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Tracks active WebSocket connections and provides broadcast helpers."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}  # trace_id → socket
        self._all: list[WebSocket] = []

    async def connect(self, ws: WebSocket, trace_id: str | None = None) -> None:
        await ws.accept()
        self._all.append(ws)
        if trace_id:
            self._connections[trace_id] = ws

    def disconnect(self, ws: WebSocket, trace_id: str | None = None) -> None:
        if ws in self._all:
            self._all.remove(ws)
        if trace_id and trace_id in self._connections:
            del self._connections[trace_id]

    async def send(self, ws: WebSocket, event: dict[str, Any]) -> None:
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json(event)
        except Exception as exc:
            logger.warning("WS send failed: %s", exc)

    async def broadcast(self, event: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._all):
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(event)
                else:
                    dead.append(ws)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._all:
                self._all.remove(ws)

    def active_count(self) -> int:
        return len(self._all)


_manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    return _manager


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


_classifier = IntentClassifier()
_planner = PlanDecomposer()


@ws_router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """
    Connect and send JSON messages: ``{"prompt": "..."}``

    Events streamed back:
        classifying, intent_classified, planning, plan_created,
        step_started, step_completed, step_failed,
        plan_completed, approval_required, error
    """
    trace_id: str | None = None

    await _manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            prompt = payload.get("prompt", "").strip()

            if not prompt:
                await _manager.send(websocket, {"event": "error", "detail": "Empty prompt"})
                continue

            # ── Classify ───────────────────────────────────────────────
            await _manager.send(websocket, {"event": "classifying"})
            intent = await _classifier.classify(prompt)

            await _manager.send(
                websocket,
                {
                    "event": "intent_classified",
                    "intent": intent.intent_type.value,
                    "confidence": intent.confidence,
                    "risk_level": intent.risk_level.value,
                },
            )

            # ── Plan ───────────────────────────────────────────────────
            await _manager.send(websocket, {"event": "planning"})
            plan = await _planner.decompose(intent)
            trace_id = plan.trace_id

            await _manager.send(
                websocket,
                {
                    "event": "plan_created",
                    "plan_id": plan.id,
                    "trace_id": trace_id,
                    "step_count": len(plan.steps),
                    "requires_approval": plan.requires_approval,
                },
            )

            # ── Approval gate ──────────────────────────────────────────
            if plan.requires_approval:
                await _manager.send(
                    websocket,
                    {
                        "event": "approval_required",
                        "plan_id": plan.id,
                        "trace_id": trace_id,
                        "steps": [
                            {"id": s.id, "description": s.description, "tool": s.tool}
                            for s in plan.steps
                        ],
                    },
                )
                continue

            # ── Execute ────────────────────────────────────────────────
            from nexus.core.executor import PlanExecutor

            executor = PlanExecutor()
            for step in plan.steps:
                await _manager.send(
                    websocket,
                    {
                        "event": "step_started",
                        "step_id": step.id,
                        "tool": step.tool,
                        "trace_id": trace_id,
                    },
                )

            try:
                response = await executor.execute(plan)

                for step in plan.steps:
                    status = step.status.value
                    event_name = "step_completed" if status == "completed" else "step_failed"
                    await _manager.send(
                        websocket,
                        {
                            "event": event_name,
                            "step_id": step.id,
                            "tool": step.tool,
                            "status": status,
                            "trace_id": trace_id,
                        },
                    )

                await _manager.send(
                    websocket,
                    {
                        "event": "plan_completed",
                        "plan_id": plan.id,
                        "trace_id": trace_id,
                        "answer": response.answer,
                        "latency_ms": response.latency_ms,
                    },
                )

            except Exception as exc:
                await _manager.send(
                    websocket,
                    {"event": "error", "detail": str(exc), "trace_id": trace_id},
                )

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await _manager.send(websocket, {"event": "error", "detail": str(exc)})
        except Exception:
            pass
    finally:
        _manager.disconnect(websocket, trace_id)
