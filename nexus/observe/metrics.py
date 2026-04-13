"""Prometheus metrics for prompts, steps, LLM calls, and connectors."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Centralised Prometheus metrics for the Nexus platform.

    Pass a custom ``registry`` in tests to avoid duplicate-registration
    errors across the default global CollectorRegistry.

    Example (tests)::

        from prometheus_client import CollectorRegistry
        collector = MetricsCollector(registry=CollectorRegistry())
    """

    def __init__(self, registry=None) -> None:
        self._registry = registry
        self._available = False
        self._init_metrics()

    def _init_metrics(self) -> None:
        try:
            from prometheus_client import Counter, Gauge, Histogram

            kw: dict = {"registry": self._registry} if self._registry is not None else {}

            self.prompts_total = Counter(
                "nexus_prompts_total",
                "Total prompts received",
                ["intent_type"],
                **kw,
            )
            self.prompt_latency = Histogram(
                "nexus_prompt_latency_seconds",
                "End-to-end prompt latency in seconds",
                ["intent_type"],
                buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
                **kw,
            )
            self.steps_total = Counter(
                "nexus_steps_total",
                "Total step executions",
                ["status", "tool"],
                **kw,
            )
            self.step_duration = Histogram(
                "nexus_step_duration_seconds",
                "Step execution duration",
                ["tool"],
                buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0),
                **kw,
            )
            self.llm_calls_total = Counter(
                "nexus_llm_calls_total",
                "Total LLM API calls",
                ["model", "purpose"],
                **kw,
            )
            self.llm_tokens_used = Counter(
                "nexus_llm_tokens_used_total",
                "Total LLM tokens consumed",
                ["model", "type"],
                **kw,
            )
            self.llm_latency = Histogram(
                "nexus_llm_latency_seconds",
                "LLM call latency",
                ["model"],
                buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 15.0, 60.0),
                **kw,
            )
            self.connector_calls_total = Counter(
                "nexus_connector_calls_total",
                "Total connector calls",
                ["connector", "action", "status"],
                **kw,
            )
            self.active_plans = Gauge(
                "nexus_active_plans",
                "Plans currently executing",
                **kw,
            )
            self.approval_pending = Gauge(
                "nexus_approval_pending",
                "Plans awaiting human approval",
                **kw,
            )

            self._available = True

        except ImportError:
            logger.warning("prometheus_client not installed — metrics disabled")
        except Exception as exc:
            logger.warning("Failed to initialise metrics: %s", exc)

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_prompt(self, intent_type: str, latency_seconds: float) -> None:
        if not self._available:
            return
        try:
            self.prompts_total.labels(intent_type=intent_type).inc()
            self.prompt_latency.labels(intent_type=intent_type).observe(latency_seconds)
        except Exception as exc:
            logger.debug("Metrics error: %s", exc)

    def record_step(self, tool: str, status: str, duration_seconds: float) -> None:
        if not self._available:
            return
        try:
            self.steps_total.labels(status=status, tool=tool).inc()
            self.step_duration.labels(tool=tool).observe(duration_seconds)
        except Exception as exc:
            logger.debug("Metrics error: %s", exc)

    def record_llm_call(
        self,
        model: str,
        purpose: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_seconds: float,
    ) -> None:
        if not self._available:
            return
        try:
            self.llm_calls_total.labels(model=model, purpose=purpose).inc()
            self.llm_tokens_used.labels(model=model, type="prompt").inc(prompt_tokens)
            self.llm_tokens_used.labels(model=model, type="completion").inc(completion_tokens)
            self.llm_latency.labels(model=model).observe(latency_seconds)
        except Exception as exc:
            logger.debug("Metrics error: %s", exc)

    def record_connector_call(self, connector: str, action: str, status: str) -> None:
        if not self._available:
            return
        try:
            self.connector_calls_total.labels(
                connector=connector, action=action, status=status
            ).inc()
        except Exception as exc:
            logger.debug("Metrics error: %s", exc)

    def set_active_plans(self, count: int) -> None:
        if not self._available:
            return
        try:
            self.active_plans.set(count)
        except Exception as exc:
            logger.debug("Metrics error: %s", exc)

    def set_approval_pending(self, count: int) -> None:
        if not self._available:
            return
        try:
            self.approval_pending.set(count)
        except Exception as exc:
            logger.debug("Metrics error: %s", exc)


def start_metrics_server(port: int = 9090) -> None:
    try:
        from prometheus_client import start_http_server
        start_http_server(port)
        logger.info("Prometheus metrics server started on :%d", port)
    except Exception as exc:
        logger.warning("Could not start metrics server: %s", exc)
