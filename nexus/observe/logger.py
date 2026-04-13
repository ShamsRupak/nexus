"""Production-grade structured logging with trace ID propagation."""

from __future__ import annotations

import logging
import sys
import uuid
from typing import Any

import structlog


def configure_logging(level: str = "INFO", force_json: bool = False) -> None:
    """Configure structlog for the entire process.

    In TTY environments (dev), output is pretty-printed.
    In non-TTY / production (force_json=True), output is JSON.
    """
    is_tty = sys.stderr.isatty() and not force_json

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        # Note: add_logger_name requires stdlib loggers; omit with PrintLoggerFactory
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    if is_tty:
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging so third-party libs flow through structlog
    logging.basicConfig(
        level=logging.getLevelName(level.upper()),
        stream=sys.stderr,
        format="%(message)s",
    )


# ---------------------------------------------------------------------------
# NexusLogger — thin wrapper that binds component + trace_id
# ---------------------------------------------------------------------------


class NexusLogger:
    """Structured logger that carries component and trace_id context."""

    def __init__(self, component: str, _log: Any = None) -> None:
        self._component = component
        self._log = _log or structlog.get_logger(component)

    def bind_trace(self, trace_id: str) -> NexusLogger:
        """Return a new NexusLogger bound to the given trace_id."""
        bound = self._log.bind(trace_id=trace_id, component=self._component)
        return NexusLogger(self._component, _log=bound)

    def bind(self, **kwargs: Any) -> NexusLogger:
        """Return a new NexusLogger with extra fields bound."""
        bound = self._log.bind(**kwargs)
        return NexusLogger(self._component, _log=bound)

    # ---- standard log levels -----------------------------------------------

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log.debug(event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log.info(event, **kwargs)

    def warn(self, event: str, **kwargs: Any) -> None:
        self._log.warning(event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._log.error(event, **kwargs)

    # ---- step lifecycle helpers --------------------------------------------

    def step_started(self, step_id: str, tool: str, **kwargs: Any) -> None:
        self._log.info(
            "step_started",
            step_id=step_id,
            tool=tool,
            **kwargs,
        )

    def step_completed(self, step_id: str, duration_ms: float, **kwargs: Any) -> None:
        self._log.info(
            "step_completed",
            step_id=step_id,
            duration_ms=round(duration_ms, 2),
            **kwargs,
        )

    def step_failed(self, step_id: str, error: str, **kwargs: Any) -> None:
        self._log.error(
            "step_failed",
            step_id=step_id,
            error=error,
            **kwargs,
        )

    # ---- plan lifecycle helpers --------------------------------------------

    def plan_created(self, plan_id: str, intent: str, step_count: int) -> None:
        self._log.info(
            "plan_created",
            plan_id=plan_id,
            intent=intent,
            step_count=step_count,
        )

    def plan_completed(self, plan_id: str, latency_ms: float) -> None:
        self._log.info(
            "plan_completed",
            plan_id=plan_id,
            latency_ms=round(latency_ms, 2),
        )


def get_logger(component: str) -> NexusLogger:
    """Get a NexusLogger for the given component name."""
    return NexusLogger(component)


def new_trace_id() -> str:
    return str(uuid.uuid4())
