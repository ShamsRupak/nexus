"""NL-to-SQL PostgreSQL connector."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PostgresConnector:
    """Executes SQL queries against a PostgreSQL database."""

    def __init__(self, connection_url: str) -> None:
        self._url = connection_url
        self._engine = None

    async def connect(self) -> None:
        try:
            from sqlalchemy.ext.asyncio import create_async_engine

            self._engine = create_async_engine(self._url, echo=False)
            logger.info("PostgreSQL connector connected")
        except Exception as exc:
            logger.warning("PostgreSQL connection failed: %s", exc)

    async def query(self, sql: str, params: dict | None = None) -> list[dict[str, Any]]:
        if self._engine is None:
            raise RuntimeError("Connector not connected — call connect() first")
        async with self._engine.connect() as conn:
            from sqlalchemy import text

            result = await conn.execute(text(sql), params or {})
            rows = result.fetchall()
            keys = list(result.keys())
            return [dict(zip(keys, row)) for row in rows]

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()
