"""FastAPI application — lifespan, middleware, routes, metrics endpoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from nexus.api.routes import router, get_plan_store, get_audit_store_ref
from nexus.api.ws import ws_router
from nexus.config import get_settings
from nexus.observe.logger import configure_logging, get_logger

_log = get_logger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(level=settings.log_level)
    _log.info("nexus_starting", env=settings.nexus_env, model=settings.llm_model)
    yield
    _log.info("nexus_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Nexus",
        description="Enterprise AI agent orchestration platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — configurable via env in production
    cors_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routes ──────────────────────────────────────────────────────────
    app.include_router(router, prefix="/api/v1")
    app.include_router(ws_router)

    # ── Prometheus /metrics ─────────────────────────────────────────────
    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest, REGISTRY
            data = generate_latest(REGISTRY)
            return Response(content=data, media_type=CONTENT_TYPE_LATEST)
        except Exception:
            return Response(content="# metrics unavailable\n", media_type="text/plain")

    return app


app = create_app()
