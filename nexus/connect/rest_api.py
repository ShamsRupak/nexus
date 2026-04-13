"""Generic REST API adapter with auth, rate limiting, and retry."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

from nexus.connect.registry import BaseConnector

logger = logging.getLogger(__name__)


class AuthType(str, Enum):
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"


@dataclass
class EndpointConfig:
    name: str
    base_url: str
    auth_type: AuthType = AuthType.NONE
    auth_token: str = ""
    api_key_header: str = "X-API-Key"
    extra_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    max_rps: float = 10.0  # max requests per second


class _TokenBucket:
    """Simple token bucket for per-endpoint rate limiting."""

    def __init__(self, rate: float) -> None:
        self._rate = rate          # tokens per second
        self._tokens = rate        # start full
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)


# Retry on these status codes
_RETRIABLE = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3


class RestApiConnector(BaseConnector):
    """Generic REST API adapter supporting multiple named endpoints."""

    name = "rest_api"
    description = (
        "Call external REST APIs (Salesforce, Jira, Slack, or any HTTP endpoint). "
        "Supports GET, POST, PUT, DELETE with bearer/api_key auth."
    )

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._endpoints: dict[str, EndpointConfig] = {}
        self._buckets: dict[str, _TokenBucket] = {}
        self._client = client  # Injected for testing

        # Register built-in mock endpoint configs
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register_endpoint(
            EndpointConfig(
                name="mock_salesforce",
                base_url="https://mock.salesforce.example.com",
                auth_type=AuthType.BEARER,
                auth_token="SALESFORCE_TOKEN",
            )
        )
        self.register_endpoint(
            EndpointConfig(
                name="mock_jira",
                base_url="https://mock.jira.example.com",
                auth_type=AuthType.API_KEY,
                auth_token="JIRA_API_KEY",
                api_key_header="Authorization",
            )
        )

    def register_endpoint(self, config: EndpointConfig) -> None:
        self._endpoints[config.name] = config
        self._buckets[config.name] = _TokenBucket(config.max_rps)

    def get_capabilities(self) -> list[str]:
        return ["get", "post", "put", "delete"]

    async def health_check(self) -> bool:
        return True  # REST connector is always "available"; individual endpoints may fail

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a REST call.

        params:
            endpoint: registered endpoint name (optional, uses base_url if omitted)
            base_url: direct URL override
            path: URL path appended to base_url
            method: HTTP method (default: action)
            payload: request body for POST/PUT
            query_params: URL query parameters
        """
        endpoint_name = params.get("endpoint")
        config = self._endpoints.get(endpoint_name) if endpoint_name else None

        base_url = (config.base_url if config else params.get("base_url", "")).rstrip("/")
        path = params.get("path", "").lstrip("/")
        url = f"{base_url}/{path}" if path else base_url

        method = (params.get("method") or action).upper()
        payload = params.get("payload")
        query = params.get("query_params", {})

        headers = self._build_headers(config)

        # Rate limit
        if endpoint_name and endpoint_name in self._buckets:
            await self._buckets[endpoint_name].acquire()

        return await self._request_with_retry(method, url, headers, payload, query, config)

    def _build_headers(self, config: EndpointConfig | None) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if config is None:
            return headers
        headers.update(config.extra_headers)
        if config.auth_type == AuthType.BEARER and config.auth_token:
            headers["Authorization"] = f"Bearer {config.auth_token}"
        elif config.auth_type == AuthType.API_KEY and config.auth_token:
            headers[config.api_key_header] = config.auth_token
        return headers

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        headers: dict,
        payload: dict | None,
        query: dict,
        config: EndpointConfig | None,
    ) -> dict[str, Any]:
        timeout = config.timeout_seconds if config else 30.0
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._do_request(method, url, headers, payload, query, timeout)

                if resp.status_code in _RETRIABLE:
                    backoff = 2**attempt
                    logger.warning(
                        "HTTP %d from %s — retry %d in %ds", resp.status_code, url, attempt + 1, backoff
                    )
                    await asyncio.sleep(backoff)
                    continue

                resp.raise_for_status()
                try:
                    data = resp.json()
                except Exception:
                    data = resp.text

                return {"success": True, "status_code": resp.status_code, "data": data}

            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("Request to %s timed out (attempt %d)", url, attempt + 1)
                await asyncio.sleep(2**attempt)
            except httpx.HTTPStatusError as exc:
                return {
                    "success": False,
                    "status_code": exc.response.status_code,
                    "error": str(exc),
                }
            except Exception as exc:
                last_exc = exc
                logger.warning("Request error (attempt %d): %s", attempt + 1, exc)
                await asyncio.sleep(2**attempt)

        return {"success": False, "error": str(last_exc)}

    async def _do_request(
        self,
        method: str,
        url: str,
        headers: dict,
        payload: dict | None,
        query: dict,
        timeout: float,
    ) -> httpx.Response:
        if self._client:
            req = self._client.build_request(
                method, url, headers=headers, json=payload, params=query
            )
            return await self._client.send(req)
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.request(
                method, url, headers=headers, json=payload, params=query
            )
