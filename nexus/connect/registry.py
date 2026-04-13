"""Connector plugin registry with capability discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Abstract base class all enterprise connectors must implement."""

    name: str
    description: str  # Used by the planner to select the right connector

    @abstractmethod
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an action with the given params.

        Args:
            action: One of the strings returned by get_capabilities().
            params: Action-specific parameters.

        Returns:
            dict with at minimum {"success": bool, "data": Any}.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the connector can reach its backend."""

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """Return the list of action names this connector supports."""


class ConnectorRegistry:
    """Singleton registry for BaseConnector plugins.

    Usage:
        registry = ConnectorRegistry()
        registry.register(MyConnector())
        conn = registry.get("my_connector")
        caps = registry.list_connectors()  # [{name, description, capabilities}]
    """

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        """Register a connector under its declared name."""
        self._connectors[connector.name] = connector

    def get(self, name: str) -> BaseConnector | None:
        """Retrieve a connector by name, or None if not registered."""
        return self._connectors.get(name)

    def list_connectors(self) -> list[dict[str, Any]]:
        """Return metadata for all registered connectors."""
        return [
            {
                "name": c.name,
                "description": c.description,
                "capabilities": c.get_capabilities(),
            }
            for c in self._connectors.values()
        ]

    def names(self) -> list[str]:
        """Return all registered connector names."""
        return list(self._connectors.keys())

    def __len__(self) -> int:
        return len(self._connectors)


# Module-level singleton
_registry = ConnectorRegistry()


def get_registry() -> ConnectorRegistry:
    return _registry
