"""Convert enterprise data to training format (instruction-response pairs)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TrainingDataGenerator:
    """Generates instruction-tuning datasets from enterprise data sources."""

    def generate_from_qa_pairs(
        self,
        pairs: list[dict[str, str]],
        output_path: str | Path,
    ) -> int:
        records = [
            {"instruction": p["question"], "response": p["answer"]}
            for p in pairs
            if "question" in p and "answer" in p
        ]
        Path(output_path).write_text(
            "\n".join(json.dumps(r) for r in records),
            encoding="utf-8",
        )
        return len(records)
