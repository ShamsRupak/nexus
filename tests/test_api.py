"""Tests for the FastAPI backend — routes and WebSocket. (10+ tests)"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")


# Use starlette TestClient (synchronous, handles lifespan correctly)
from starlette.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from nexus.api.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ===========================================================================
# HEALTH & INFRA
# ===========================================================================


def test_health_returns_ok(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "components" in data


def test_metrics_endpoint_returns_prometheus_format(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    # Prometheus format starts with # HELP or metric name lines
    assert resp.headers["content-type"].startswith("text/plain")


def test_connectors_endpoint(client):
    resp = client.get("/api/v1/connectors")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ===========================================================================
# PROMPT ENDPOINT
# ===========================================================================


def test_post_prompt_query_returns_completed(client):
    resp = client.post("/api/v1/prompt", json={"prompt": "show me all deals"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert "plan_id" in data
    assert data["result"] is not None


def test_post_prompt_action_returns_awaiting_approval(client):
    resp = client.post("/api/v1/prompt", json={"prompt": "create a new customer record"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "awaiting_approval"
    assert "steps" in data
    assert len(data["steps"]) > 0


def test_post_prompt_empty_raises_422(client):
    resp = client.post("/api/v1/prompt", json={"prompt": ""})
    assert resp.status_code == 422


def test_post_prompt_with_user_id(client):
    resp = client.post(
        "/api/v1/prompt",
        json={"prompt": "list all customers", "user_id": "user-123"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


# ===========================================================================
# PLAN APPROVAL
# ===========================================================================


def test_approve_nonexistent_plan_returns_404(client):
    resp = client.post("/api/v1/approve/nonexistent-plan-id")
    assert resp.status_code == 404


def test_approve_pending_plan_executes(client):
    # First submit an action prompt to get a pending plan
    resp = client.post("/api/v1/prompt", json={"prompt": "delete all records"})
    assert resp.status_code == 200
    data = resp.json()

    if data["status"] == "awaiting_approval":
        plan_id = data["plan_id"]
        approve_resp = client.post(f"/api/v1/approve/{plan_id}")
        assert approve_resp.status_code == 200
        result = approve_resp.json()
        assert result["status"] == "completed"
        assert result["plan_id"] == plan_id


# ===========================================================================
# PLANS LIST
# ===========================================================================


def test_get_plans_returns_list(client):
    # Submit a prompt first to populate
    client.post("/api/v1/prompt", json={"prompt": "show me all deals"})
    resp = client.get("/api/v1/plans")
    assert resp.status_code == 200
    plans = resp.json()
    assert isinstance(plans, list)
    assert len(plans) >= 1


def test_get_plans_respects_limit(client):
    resp = client.get("/api/v1/plans?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) <= 2


# ===========================================================================
# AUDIT TRAIL
# ===========================================================================


def test_get_audit_returns_entries(client):
    # Submit a prompt to generate an audit entry
    client.post("/api/v1/prompt", json={"prompt": "show all customers"})
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 200
    entries = resp.json()
    assert isinstance(entries, list)
    # At least one entry should exist from our prompts above
    assert len(entries) >= 1


def test_get_audit_export_json(client):
    client.post("/api/v1/prompt", json={"prompt": "list deals"})
    resp = client.get("/api/v1/audit/export?fmt=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["format"] == "json"
    assert "content" in data
    assert data["entry_count"] >= 1


def test_get_audit_export_csv(client):
    resp = client.get("/api/v1/audit/export?fmt=csv")
    assert resp.status_code == 200
    data = resp.json()
    assert data["format"] == "csv"


def test_get_audit_export_invalid_format(client):
    resp = client.get("/api/v1/audit/export?fmt=xml")
    assert resp.status_code == 422


# ===========================================================================
# EVAL REPORT
# ===========================================================================


def test_eval_report_endpoint(client):
    resp = client.get("/api/v1/eval/report")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "passed" in data
    assert "pass_rate" in data
    assert data["total"] == 3  # 3 built-in cases


# ===========================================================================
# WEBSOCKET
# ===========================================================================


def test_websocket_query_streams_events(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"prompt": "show me all deals"})

        events = []
        for _ in range(10):  # collect up to 10 events
            try:
                msg = ws.receive_json()
                events.append(msg["event"])
                if msg["event"] in ("plan_completed", "error"):
                    break
            except Exception:
                break

    assert "classifying" in events
    assert "intent_classified" in events
    assert "plan_created" in events


def test_websocket_action_sends_approval_required(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"prompt": "create a new customer record"})

        events = []
        for _ in range(10):
            try:
                msg = ws.receive_json()
                events.append(msg["event"])
                if msg["event"] in ("approval_required", "plan_completed", "error"):
                    break
            except Exception:
                break

    assert "approval_required" in events


def test_websocket_empty_prompt_returns_error(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"prompt": ""})
        msg = ws.receive_json()
    assert msg["event"] == "error"
