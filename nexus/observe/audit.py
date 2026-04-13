"""Append-only audit trail for enterprise compliance."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    """Immutable record of a single agent action."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user_id: str | None = None
    action_type: str  # "query" | "create" | "update" | "delete" | "approve"
    connector: str
    input_summary: str   # truncated for security
    output_summary: str  # truncated
    approval_status: str  # "auto_approved" | "human_approved" | "pending" | "rejected"
    risk_level: str      # "low" | "medium" | "high"
    duration_ms: float

    model_config = {"frozen": True}


class AuditStore:
    """Thread-safe in-memory audit store with optional JSONL file persistence."""

    _MAX_SUMMARY_LEN = 500

    def __init__(self, persist_path: str | Path | None = None) -> None:
        self._entries: list[AuditEntry] = []
        self._path = Path(persist_path) if persist_path else None

        # Replay persisted entries on startup
        if self._path and self._path.exists():
            self._load_from_file()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        trace_id: str,
        action_type: str,
        connector: str,
        input_text: str,
        output_text: str,
        approval_status: str = "auto_approved",
        risk_level: str = "low",
        duration_ms: float = 0.0,
        user_id: str | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            trace_id=trace_id,
            user_id=user_id,
            action_type=action_type,
            connector=connector,
            input_summary=input_text[: self._MAX_SUMMARY_LEN],
            output_summary=output_text[: self._MAX_SUMMARY_LEN],
            approval_status=approval_status,
            risk_level=risk_level,
            duration_ms=duration_ms,
        )
        self._entries.append(entry)
        if self._path:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(entry.model_dump_json() + "\n")
        return entry

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query_audit(
        self,
        trace_id: str | None = None,
        user_id: str | None = None,
        action_type: str | None = None,
        connector: str | None = None,
        risk_level: str | None = None,
        approval_status: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        results = self._entries

        if trace_id:
            results = [e for e in results if e.trace_id == trace_id]
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if action_type:
            results = [e for e in results if e.action_type == action_type]
        if connector:
            results = [e for e in results if e.connector == connector]
        if risk_level:
            results = [e for e in results if e.risk_level == risk_level]
        if approval_status:
            results = [e for e in results if e.approval_status == approval_status]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if until:
            results = [e for e in results if e.timestamp <= until]

        # Most recent first
        return list(reversed(results))[:limit]

    def all_entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def count(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_audit(self, fmt: str = "json") -> str:
        """Export all entries as JSON or CSV string."""
        if fmt == "json":
            return json.dumps(
                [json.loads(e.model_dump_json()) for e in self._entries],
                indent=2,
                default=str,
            )

        if fmt == "csv":
            if not self._entries:
                return ""
            buf = io.StringIO()
            fields = list(AuditEntry.model_fields.keys())
            writer = csv.DictWriter(buf, fieldnames=fields)
            writer.writeheader()
            for entry in self._entries:
                row = json.loads(entry.model_dump_json())
                writer.writerow(row)
            return buf.getvalue()

        raise ValueError(f"Unknown export format: {fmt!r}. Use 'json' or 'csv'.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_from_file(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:  # type: ignore[arg-type]
                for line in f:
                    line = line.strip()
                    if line:
                        self._entries.append(AuditEntry.model_validate_json(line))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Could not load audit file: %s", exc)

    def clear(self) -> None:
        """Clear all in-memory entries (does not delete persisted file)."""
        self._entries.clear()


# Module-level singleton (replaces old AuditLogger stub)
_store = AuditStore()


def get_audit_store() -> AuditStore:
    return _store
