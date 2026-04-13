"""Generic REST API adapter."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RestApiConnector:
    """Generic REST API connector with auth support."""

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._timeout = timeout

    async def get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = client.get(
                f"{self._base_url}/{path.lstrip('/')}",
                headers=self._headers,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def post(self, path: str, payload: dict) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/{path.lstrip('/')}",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
