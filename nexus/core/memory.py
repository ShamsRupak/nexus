"""Conversation memory and fact extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MemoryEntry:
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tags: list[str] = field(default_factory=list)


class ConversationMemory:
    """Stores conversation history and extracted facts."""

    def __init__(self, max_entries: int = 100) -> None:
        self._entries: list[MemoryEntry] = []
        self._max_entries = max_entries

    def add(self, content: str, tags: list[str] | None = None) -> None:
        entry = MemoryEntry(content=content, tags=tags or [])
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries.pop(0)

    def recent(self, n: int = 10) -> list[MemoryEntry]:
        return self._entries[-n:]

    def clear(self) -> None:
        self._entries.clear()
