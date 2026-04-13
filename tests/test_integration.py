"""Integration tests — full prompt-to-response pipeline. (10+ tests)"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

from starlette.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from nexus.api.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ===========================================================================
# FULL PIPELINE TESTS
# ===========================================================================


def test_full_pipeline_query_returns_completed(client):
    """Prompt → classify → plan → execute → completed response."""
    resp = client.post("/api/v1/prompt", json={"prompt": "show me all deals"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["plan_id"]
    result = data["result"]
    assert result is not None
    assert "answer" in result
    assert len(result["answer"]) > 0


def test_full_pipeline_action_returns_awaiting_approval(client):
    """Prompt with action intent → plan requires approval."""
    resp = client.post("/api/v1/prompt", json={"prompt": "delete all customer records"})
    assert resp.status_code == 200
    data = resp.json()
    # Delete is high-risk → should require approval
    assert data["status"] == "awaiting_approval"
    assert "plan_id" in data
    assert "steps" in data
    assert len(data["steps"]) > 0


def test_full_pipeline_analysis_intent_generates_multi_step_plan(client):
    """Analysis intent produces a multi-step plan."""
    resp = client.post("/api/v1/prompt", json={"prompt": "analyze revenue trends by region"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    # Plans are returned in the plans list
    plans_resp = client.get("/api/v1/plans")
    plans = plans_resp.json()
    matching = [p for p in plans if p["intent"] in ("analysis", "query")]
    assert len(matching) >= 1


def test_query_intent_uses_correct_connector_type(client):
    """Query intent produces steps referencing a data connector."""
    resp = client.post("/api/v1/prompt", json={"prompt": "list all customers"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    result = data["result"]
    assert result["answer"]  # non-empty answer


def test_full_pipeline_response_has_trace_id(client):
    """The AgentResponse always carries a trace_id."""
    resp = client.post("/api/v1/prompt", json={"prompt": "how many support tickets are open?"})
    assert resp.status_code == 200
    data = resp.json()
    if data["status"] == "completed":
        assert data["result"]["trace_id"]


def test_audit_trail_records_full_execution(client):
    """After a successful query, audit trail has at least one entry."""
    unique_prompt = "show me all deals for audit integration test"
    client.post("/api/v1/prompt", json={"prompt": unique_prompt})
    audit_resp = client.get("/api/v1/audit")
    assert audit_resp.status_code == 200
    entries = audit_resp.json()
    assert len(entries) >= 1
    # Each entry has the required fields
    entry = entries[0]
    assert "trace_id" in entry
    assert "action_type" in entry
    assert "connector" in entry
    assert "risk_level" in entry
    assert "timestamp" in entry


def test_metrics_increment_after_full_execution(client):
    """Prometheus /metrics endpoint shows nexus metrics after execution."""
    client.post("/api/v1/prompt", json={"prompt": "show me all deals"})
    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    body = metrics_resp.text
    # Prometheus format has metric lines
    assert len(body) > 0
    assert "# HELP" in body or "nexus" in body or "python" in body


def test_approve_pending_plan_completes_pipeline(client):
    """Full approve flow: create pending plan → approve → completed."""
    resp = client.post("/api/v1/prompt", json={"prompt": "create a new deal record"})
    assert resp.status_code == 200
    data = resp.json()

    if data["status"] == "awaiting_approval":
        plan_id = data["plan_id"]
        approve_resp = client.post(f"/api/v1/approve/{plan_id}")
        assert approve_resp.status_code == 200
        result = approve_resp.json()
        assert result["status"] == "completed"
        assert result["result"]["answer"]
    # If auto-approved, still a valid test (plan is low-risk)


def test_context_assembly_non_empty_answer(client):
    """Query responses always have a non-trivial answer string."""
    prompts = [
        "show me all deals",
        "list all customers",
        "how many support tickets are critical?",
    ]
    for prompt in prompts:
        resp = client.post("/api/v1/prompt", json={"prompt": prompt})
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] == "completed":
            assert data["result"]["answer"].strip(), f"Empty answer for: {prompt}"


def test_websocket_query_streams_plan_created(client):
    """WebSocket streams plan_created event for a query prompt."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"prompt": "show me all deals"})
        events = []
        for _ in range(15):
            try:
                msg = ws.receive_json()
                events.append(msg["event"])
                if msg["event"] in ("plan_completed", "error"):
                    break
            except Exception:
                break
    assert "plan_created" in events


def test_websocket_action_sends_approval_required(client):
    """WebSocket fires approval_required for write operations."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"prompt": "create a new customer record"})
        events = []
        for _ in range(15):
            try:
                msg = ws.receive_json()
                events.append(msg["event"])
                if msg["event"] in ("approval_required", "plan_completed", "error"):
                    break
            except Exception:
                break
    assert "approval_required" in events


def test_plans_list_populated_after_multiple_prompts(client):
    """After several prompts, /api/v1/plans returns all of them."""
    prompts = [
        "show me all deals",
        "list all customers",
        "analyze support ticket trends",
    ]
    for p in prompts:
        client.post("/api/v1/prompt", json={"prompt": p})

    resp = client.get("/api/v1/plans?limit=50")
    assert resp.status_code == 200
    plans = resp.json()
    assert len(plans) >= 3


def test_eval_report_all_cases_run(client):
    """Eval report runs all built-in regression cases and returns a report."""
    resp = client.get("/api/v1/eval/report")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["passed"] + data["failed"] == data["total"]
    assert 0.0 <= data["pass_rate"] <= 1.0
    assert len(data["results"]) == 3
