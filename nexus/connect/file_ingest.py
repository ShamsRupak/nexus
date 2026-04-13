"""File ingestion connector — CSV, JSON, Markdown, and plain text."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from nexus.connect.registry import BaseConnector

logger = logging.getLogger(__name__)

# Rough chunk size: ~512 words ≈ 512*5 = 2560 chars, overlap ~200 chars
_CHUNK_CHARS = 2000
_OVERLAP_CHARS = 200


class FileIngestConnector(BaseConnector):
    """Reads and parses enterprise files for agent context and vector ingestion."""

    name = "file_ingest"
    description = (
        "Parse and extract data from CSV, JSON, Markdown, and plain-text files. "
        "Returns structured data or text chunks ready for vector ingestion."
    )

    def get_capabilities(self) -> list[str]:
        return ["ingest_csv", "ingest_json", "ingest_text", "detect"]

    async def health_check(self) -> bool:
        return True

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        path = params.get("path", "")
        if action == "ingest_csv":
            data = await self.ingest_csv(path)
            return {"success": True, "data": data}
        if action == "ingest_json":
            data = await self.ingest_json(path)
            return {"success": True, "data": data}
        if action == "ingest_text":
            chunks = await self.ingest_text(path)
            return {"success": True, "chunks": chunks, "chunk_count": len(chunks)}
        if action == "detect":
            return {"success": True, "format": self._detect_format(path)}
        raise ValueError(f"Unknown file_ingest action: {action!r}")

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    async def ingest_csv(self, path: str | Path) -> dict[str, Any]:
        """Parse CSV, returning schema metadata + row data."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")

        rows: list[dict[str, Any]] = []
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for row in reader:
                rows.append(dict(row))

        column_types = _infer_column_types(rows, list(fieldnames))

        logger.info("Ingested CSV %s: %d rows, %d cols", p.name, len(rows), len(fieldnames))
        return {
            "file": p.name,
            "format": "csv",
            "row_count": len(rows),
            "columns": list(fieldnames),
            "column_types": column_types,
            "preview": rows[:5],
            "rows": rows,
        }

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    async def ingest_json(self, path: str | Path) -> dict[str, Any]:
        """Parse a JSON file and return structured metadata."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")

        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)

        record_count: int | None = None
        keys: list[str] = []

        if isinstance(data, list):
            record_count = len(data)
            if data and isinstance(data[0], dict):
                keys = list(data[0].keys())
        elif isinstance(data, dict):
            keys = list(data.keys())

        logger.info("Ingested JSON %s: %d top-level keys", p.name, len(keys))
        return {
            "file": p.name,
            "format": "json",
            "record_count": record_count,
            "keys": keys,
            "data": data,
        }

    # ------------------------------------------------------------------
    # Text / Markdown
    # ------------------------------------------------------------------

    async def ingest_text(self, path: str | Path) -> list[str]:
        """Read a text or Markdown file and return overlapping chunks."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")

        text = p.read_text(encoding="utf-8")
        chunks = self._chunk(text)
        logger.info("Ingested text %s: %d chars → %d chunks", p.name, len(text), len(chunks))
        return chunks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _chunk(self, text: str) -> list[str]:
        """Split text into overlapping chunks by character count."""
        if len(text) <= _CHUNK_CHARS:
            return [text] if text.strip() else []

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + _CHUNK_CHARS, len(text))
            # Try to break at a paragraph or sentence boundary
            if end < len(text):
                para_break = text.rfind("\n\n", start, end)
                sent_break = text.rfind(". ", start, end)
                boundary = max(para_break, sent_break)
                if boundary > start + _CHUNK_CHARS // 2:
                    end = boundary + 1  # include the break character

            chunks.append(text[start:end].strip())
            if end >= len(text):
                break
            start = max(start + 1, end - _OVERLAP_CHARS)

        return [c for c in chunks if c]

    @staticmethod
    def _detect_format(path: str) -> str:
        ext = Path(path).suffix.lower()
        return {".csv": "csv", ".json": "json", ".md": "markdown", ".txt": "text"}.get(
            ext, "unknown"
        )


def _infer_column_types(rows: list[dict], columns: list[str]) -> dict[str, str]:
    """Best-effort type inference from a sample of rows."""
    types: dict[str, str] = {}
    for col in columns:
        sample = [r[col] for r in rows[:20] if col in r and r[col] not in ("", None)]
        if not sample:
            types[col] = "unknown"
            continue
        if all(_is_int(v) for v in sample):
            types[col] = "integer"
        elif all(_is_float(v) for v in sample):
            types[col] = "float"
        else:
            types[col] = "string"
    return types


def _is_int(v: str) -> bool:
    try:
        int(v)
        return True
    except (ValueError, TypeError):
        return False


def _is_float(v: str) -> bool:
    try:
        float(v)
        return True
    except (ValueError, TypeError):
        return False
