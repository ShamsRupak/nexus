"""Action audit trail."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AuditEvent:
    trace_id: str
    plan_id: str
    step_id: str
    tool: str
    action: str
    status: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: dict = field(default_factory=dict)


class AuditLogger:
    """Writes audit events to a JSONL file and/or stdout."""

    def __init__(self, output_path: str | Path | None = None) -> None:
        self._path = Path(output_path) if output_path else None

    def log(self, event: AuditEvent) -> None:
        record = json.dumps(asdict(event))
        logger.info("AUDIT %s", record)
        if self._path:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(record + "\n")
