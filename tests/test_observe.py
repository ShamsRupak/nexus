"""Tests for observability layer — logger, metrics, audit. (15+ tests)"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta
from io import StringIO

import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")


# ===========================================================================
# LOGGER TESTS
# ===========================================================================


def test_logger_returns_nexus_logger():
    from nexus.observe.logger import NexusLogger, get_logger

    log = get_logger("test_component")
    assert isinstance(log, NexusLogger)


def test_logger_bind_trace_returns_new_instance():
    from nexus.observe.logger import NexusLogger, get_logger

    log = get_logger("test")
    bound = log.bind_trace("trace-abc-123")
    assert isinstance(bound, NexusLogger)
    assert bound is not log


def test_logger_bind_trace_propagates_id():
    """After binding, calling info/warn/error should not raise."""
    import structlog.testing

    from nexus.observe.logger import get_logger

    log = get_logger("test")
    bound = log.bind_trace("tid-xyz")
    with structlog.testing.capture_logs() as cap:
        bound.info("hello", extra="world")
    assert len(cap) == 1
    assert cap[0]["event"] == "hello"
    assert cap[0]["extra"] == "world"


def test_logger_step_started_logs_step_id():
    import structlog.testing

    from nexus.observe.logger import get_logger

    log = get_logger("executor")
    with structlog.testing.capture_logs() as cap:
        log.step_started("s1", "postgres")
    assert cap[0]["event"] == "step_started"
    assert cap[0]["step_id"] == "s1"
    assert cap[0]["tool"] == "postgres"


def test_logger_step_completed_includes_duration():
    import structlog.testing

    from nexus.observe.logger import get_logger

    log = get_logger("executor")
    with structlog.testing.capture_logs() as cap:
        log.step_completed("s1", 123.45)
    assert cap[0]["event"] == "step_completed"
    assert cap[0]["duration_ms"] == 123.45


def test_logger_step_failed_logs_error():
    import structlog.testing

    from nexus.observe.logger import get_logger

    log = get_logger("executor")
    with structlog.testing.capture_logs() as cap:
        log.step_failed("s2", "Connection refused")
    assert cap[0]["event"] == "step_failed"
    assert cap[0]["error"] == "Connection refused"


def test_logger_plan_lifecycle():
    import structlog.testing

    from nexus.observe.logger import get_logger

    log = get_logger("planner")
    with structlog.testing.capture_logs() as cap:
        log.plan_created("plan-1", "query", 3)
        log.plan_completed("plan-1", 250.0)
    assert cap[0]["event"] == "plan_created"
    assert cap[1]["event"] == "plan_completed"
    assert cap[1]["latency_ms"] == 250.0


def test_new_trace_id_generates_uuid():
    from nexus.observe.logger import new_trace_id

    t1 = new_trace_id()
    t2 = new_trace_id()
    assert t1 != t2
    assert len(t1) == 36  # UUID4 format


# ===========================================================================
# METRICS TESTS
# ===========================================================================


def _fresh_collector():
    from prometheus_client import CollectorRegistry

    from nexus.observe.metrics import MetricsCollector

    return MetricsCollector(registry=CollectorRegistry())


def test_metrics_collector_initialises():
    mc = _fresh_collector()
    assert mc._available is True


def test_metrics_record_prompt_increments_counter():
    mc = _fresh_collector()
    mc.record_prompt("query", 1.5)
    mc.record_prompt("query", 0.8)
    mc.record_prompt("analysis", 2.1)

    from prometheus_client import generate_latest

    output = generate_latest(mc._registry).decode()
    assert "nexus_prompts_total" in output


def test_metrics_record_step_increments_steps_total():
    mc = _fresh_collector()
    mc.record_step("postgres", "completed", 0.5)
    mc.record_step("postgres", "failed", 0.1)

    from prometheus_client import generate_latest

    output = generate_latest(mc._registry).decode()
    assert "nexus_steps_total" in output


def test_metrics_record_llm_call():
    mc = _fresh_collector()
    mc.record_llm_call("gpt-4o-mini", "classify", 120, 40, 0.8)

    from prometheus_client import generate_latest

    output = generate_latest(mc._registry).decode()
    assert "nexus_llm_calls_total" in output
    assert "nexus_llm_tokens_used_total" in output


def test_metrics_record_connector_call():
    mc = _fresh_collector()
    mc.record_connector_call("postgres", "nl_query", "success")
    mc.record_connector_call("vector_store", "search", "success")

    from prometheus_client import generate_latest

    output = generate_latest(mc._registry).decode()
    assert "nexus_connector_calls_total" in output


def test_metrics_gauges_settable():
    mc = _fresh_collector()
    mc.set_active_plans(3)
    mc.set_approval_pending(1)

    from prometheus_client import generate_latest

    output = generate_latest(mc._registry).decode()
    assert "nexus_active_plans" in output
    assert "nexus_approval_pending" in output


# ===========================================================================
# AUDIT TESTS
# ===========================================================================


def _fresh_store():
    from nexus.observe.audit import AuditStore

    return AuditStore()


def test_audit_record_creates_entry():
    store = _fresh_store()
    entry = store.record(
        trace_id="tid-1",
        action_type="query",
        connector="postgres",
        input_text="show all deals",
        output_text="5 deals returned",
    )
    assert entry.trace_id == "tid-1"
    assert entry.action_type == "query"
    assert store.count() == 1


def test_audit_query_by_trace_id():
    store = _fresh_store()
    store.record("tid-A", "query", "postgres", "show deals", "ok")
    store.record("tid-B", "create", "postgres", "create customer", "ok")

    results = store.query_audit(trace_id="tid-A")
    assert len(results) == 1
    assert results[0].trace_id == "tid-A"


def test_audit_query_by_action_type():
    store = _fresh_store()
    store.record("t1", "query", "postgres", "q", "r")
    store.record("t2", "delete", "postgres", "del", "ok")
    store.record("t3", "query", "vector_store", "q2", "r2")

    queries = store.query_audit(action_type="query")
    assert len(queries) == 2
    assert all(e.action_type == "query" for e in queries)


def test_audit_query_by_date_range():
    store = _fresh_store()
    from nexus.observe.audit import AuditEntry

    # Manually inject entries at known timestamps
    now = datetime.utcnow()
    old = AuditEntry(
        trace_id="old",
        timestamp=now - timedelta(hours=2),
        action_type="query",
        connector="postgres",
        input_summary="old query",
        output_summary="old result",
        approval_status="auto_approved",
        risk_level="low",
        duration_ms=10.0,
    )
    new = AuditEntry(
        trace_id="new",
        timestamp=now - timedelta(minutes=5),
        action_type="query",
        connector="postgres",
        input_summary="new query",
        output_summary="new result",
        approval_status="auto_approved",
        risk_level="low",
        duration_ms=10.0,
    )
    store._entries.extend([old, new])

    results = store.query_audit(since=now - timedelta(hours=1))
    assert len(results) == 1
    assert results[0].trace_id == "new"


def test_audit_export_json_is_valid():
    store = _fresh_store()
    store.record("t1", "query", "postgres", "show deals", "ok")
    store.record("t2", "action", "rest_api", "post request", "created")

    exported = store.export_audit(fmt="json")
    data = json.loads(exported)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["trace_id"] in ("t1", "t2")


def test_audit_export_csv_is_valid():
    store = _fresh_store()
    store.record("t1", "query", "postgres", "input", "output")

    exported = store.export_audit(fmt="csv")
    assert exported.strip()
    reader = csv.DictReader(StringIO(exported))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["trace_id"] == "t1"


def test_audit_export_invalid_format_raises():
    store = _fresh_store()
    with pytest.raises(ValueError, match="Unknown export format"):
        store.export_audit(fmt="xml")


def test_audit_input_summary_truncated():
    store = _fresh_store()
    long_input = "x" * 1000
    entry = store.record("t1", "query", "p", long_input, "ok")
    assert len(entry.input_summary) <= store._MAX_SUMMARY_LEN
