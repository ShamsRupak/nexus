"""Connector plugin registry."""

from __future__ import annotations

from typing import Any, Callable


class ConnectorRegistry:
    """Registry for enterprise data connectors."""

    def __init__(self) -> None:
        self._connectors: dict[str, Any] = {}

    def register(self, name: str, connector: Any) -> None:
        self._connectors[name] = connector

    def get(self, name: str) -> Any | None:
        return self._connectors.get(name)

    def list_connectors(self) -> list[str]:
        return list(self._connectors.keys())


_registry = ConnectorRegistry()


def get_registry() -> ConnectorRegistry:
    return _registry
