"""Prometheus metrics definitions."""

from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram, start_http_server

    request_latency = Histogram(
        "nexus_request_latency_seconds",
        "End-to-end request latency",
        ["intent_type"],
    )

    plan_total = Counter(
        "nexus_plans_total",
        "Total plans created",
        ["intent_type"],
    )

    step_success_total = Counter(
        "nexus_step_success_total",
        "Successful step executions",
        ["tool"],
    )

    step_failure_total = Counter(
        "nexus_step_failure_total",
        "Failed step executions",
        ["tool"],
    )

    def start_metrics_server(port: int = 9090) -> None:
        start_http_server(port)

except ImportError:
    def start_metrics_server(port: int = 9090) -> None:  # type: ignore[misc]
        pass
