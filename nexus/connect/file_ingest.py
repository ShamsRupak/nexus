"""CSV / PDF / document ingestion connector."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileIngestConnector:
    """Reads and parses CSV and plain-text files for agent context."""

    async def ingest_csv(self, path: str | Path) -> list[dict[str, Any]]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        rows: list[dict] = []
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        logger.info("Ingested %d rows from %s", len(rows), p.name)
        return rows

    async def ingest_text(self, path: str | Path) -> str:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        text = p.read_text(encoding="utf-8")
        logger.info("Ingested %d chars from %s", len(text), p.name)
        return text
