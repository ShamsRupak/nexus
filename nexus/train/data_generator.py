"""Convert enterprise data into instruction-tuning format (JSONL)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class TrainingDataGenerator:
    """Generate instruction/response pairs from enterprise data sources.

    Supports four generation strategies:
    - Schema-based:      column names → "What is the {col} of {entity}?" questions
    - Aggregation-based: count / sum / average / filter questions over numeric columns
    - Policy-based:      text paragraphs → Q&A pairs about policies
    - SQL-based:         natural-language questions with their SQL answers
    """

    def from_csv(self, path: str, table_name: str) -> list[dict]:
        """Generate instruction pairs from a CSV file.

        Applies schema-based, aggregation-based, and SQL strategies.
        Returns a list of {"instruction": ..., "response": ...} dicts.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"CSV not found: {path}")

        rows: list[dict[str, str]] = []
        with p.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames: list[str] = list(reader.fieldnames or [])
            for row in reader:
                rows.append(dict(row))

        if not rows:
            return []

        pairs: list[dict] = []
        pairs.extend(_schema_pairs(rows, fieldnames, table_name))
        pairs.extend(_aggregation_pairs(rows, fieldnames, table_name))
        pairs.extend(_sql_pairs(rows, fieldnames, table_name))
        return pairs

    def from_text(self, path: str, topic: str) -> list[dict]:
        """Generate Q&A pairs from a Markdown / plain-text policy document."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Text file not found: {path}")
        text = p.read_text(encoding="utf-8")
        return _policy_pairs(text, topic)

    def from_schema(self, schema: dict) -> list[dict]:
        """Generate questions from a JSON schema description.

        Expected schema format::

            {
              "table": "deals",
              "columns": [
                {"name": "deal_value", "type": "float", "description": "USD value"},
                ...
              ]
            }
        """
        table = schema.get("table", "entity")
        columns = schema.get("columns", [])
        pairs: list[dict] = []

        for col in columns:
            name: str = col.get("name", "")
            desc: str = col.get("description", name.replace("_", " "))
            dtype: str = col.get("type", "text")

            # Definition question
            pairs.append({
                "instruction": f"What does the '{name}' field represent in the {table} table?",
                "response": f"The '{name}' field in the {table} table stores the {desc}.",
            })

            if dtype in ("float", "int", "number"):
                pairs.append({
                    "instruction": f"What is the total {desc} across all {table}?",
                    "response": f"To get the total {desc}, run: SELECT SUM({name}) FROM {table};",
                })
                entity = table.rstrip("s") if table.endswith("s") else table
                pairs.append({
                    "instruction": f"What is the average {desc} per {entity}?",
                    "response": f"To get the average {desc}, run: SELECT AVG({name}) FROM {table};",
                })

        return pairs

    def export_jsonl(self, pairs: list[dict], output_path: str) -> int:
        """Write pairs to a JSONL file compatible with HuggingFace datasets.

        Returns the number of records written.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(pair, ensure_ascii=False)
            for pair in pairs
            if "instruction" in pair and "response" in pair
        ]
        out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return len(lines)

    def generate_all(self, data_dir: str, output_path: str) -> int:
        """Generate 200+ pairs from all CSV / text files under *data_dir*."""
        data_dir_path = Path(data_dir)
        all_pairs: list[dict] = []

        for csv_file in sorted(data_dir_path.glob("*.csv")):
            try:
                all_pairs.extend(self.from_csv(str(csv_file), csv_file.stem))
            except Exception:
                pass

        for md_file in sorted(data_dir_path.glob("*.md")):
            topic = md_file.stem.replace("_", " ").title()
            try:
                all_pairs.extend(self.from_text(str(md_file), topic))
            except Exception:
                pass

        return self.export_jsonl(all_pairs, output_path)


# ---------------------------------------------------------------------------
# Schema-based strategy
# ---------------------------------------------------------------------------


def _find_name_col(fieldnames: list[str]) -> str | None:
    for candidate in ("name", "company", "subject", "title"):
        if candidate in fieldnames:
            return candidate
    return None


def _schema_pairs(
    rows: list[dict[str, str]],
    fieldnames: list[str],
    table_name: str,
) -> list[dict]:
    """One question per (entity × column) for the first few rows."""
    pairs: list[dict] = []
    id_col = fieldnames[0] if fieldnames else "id"
    name_col = _find_name_col(fieldnames)

    for row in rows[:20]:
        entity_val = row.get(id_col, "")
        entity_label = row.get(name_col, entity_val) if name_col else entity_val

        for col in fieldnames[1:]:
            value = row.get(col, "")
            if not value:
                continue
            human_col = col.replace("_", " ")
            pairs.append({
                "instruction": f"What is the {human_col} of {entity_label}?",
                "response": f"The {human_col} of {entity_label} is {value}.",
            })

    return pairs


# ---------------------------------------------------------------------------
# Aggregation-based strategy
# ---------------------------------------------------------------------------


def _parse_numeric(values: list[str]) -> list[float]:
    result = []
    for v in values:
        try:
            result.append(float(str(v).replace(",", "").replace("$", "")))
        except (ValueError, AttributeError):
            pass
    return result


def _is_categorical(values: list[str]) -> bool:
    unique = {v for v in values if v}
    return 2 <= len(unique) <= max(10, int(len(values) * 0.3))


def _value_counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _aggregation_pairs(
    rows: list[dict[str, str]],
    fieldnames: list[str],
    table_name: str,
) -> list[dict]:
    """Generate count / sum / average / filter questions."""
    entity_plural = table_name if table_name.endswith("s") else table_name + "s"
    pairs: list[dict] = []

    # Total count
    pairs.append({
        "instruction": f"How many {entity_plural} are there in total?",
        "response": f"There are {len(rows)} {entity_plural} in total.",
    })

    for col in fieldnames:
        values = [r.get(col, "") for r in rows if r.get(col)]
        human_col = col.replace("_", " ")

        numeric_vals = _parse_numeric(values)
        if numeric_vals and len(numeric_vals) >= len(values) * 0.6:
            total = sum(numeric_vals)
            avg = total / len(numeric_vals)
            pairs.append({
                "instruction": f"What is the total {human_col} across all {entity_plural}?",
                "response": (
                    f"The total {human_col} across all {len(numeric_vals)} {entity_plural} "
                    f"is {total:,.2f}."
                ),
            })
            pairs.append({
                "instruction": f"What is the average {human_col} per {entity_plural.rstrip('s')}?",
                "response": (
                    f"The average {human_col} is {avg:,.2f}, "
                    f"calculated across {len(numeric_vals)} {entity_plural}."
                ),
            })
        elif _is_categorical(values):
            freq = _value_counts(values)
            top_val, top_count = max(freq.items(), key=lambda kv: kv[1])
            pairs.append({
                "instruction": f"What is the most common {human_col} among {entity_plural}?",
                "response": (
                    f"The most common {human_col} is '{top_val}' with {top_count} {entity_plural}."
                ),
            })
            for val, count in list(freq.items())[:5]:
                pairs.append({
                    "instruction": (
                        f"How many {entity_plural} have {human_col} equal to '{val}'?"
                    ),
                    "response": (
                        f"There are {count} {entity_plural} with {human_col} equal to '{val}'."
                    ),
                })

    return pairs


# ---------------------------------------------------------------------------
# SQL-based strategy
# ---------------------------------------------------------------------------


def _sql_pairs(
    rows: list[dict[str, str]],
    fieldnames: list[str],
    table_name: str,
) -> list[dict]:
    """Generate NL → SQL training pairs."""
    entity_plural = table_name if table_name.endswith("s") else table_name + "s"
    pairs: list[dict] = [
        {
            "instruction": f"Write a SQL query to retrieve all {entity_plural}.",
            "response": f"SELECT * FROM {table_name};",
        },
        {
            "instruction": f"Write a SQL query to count the number of {entity_plural}.",
            "response": f"SELECT COUNT(*) FROM {table_name};",
        },
    ]

    for col in fieldnames:
        values = [r.get(col, "") for r in rows if r.get(col)]
        if _is_categorical(values):
            freq = _value_counts(values)
            for val in list(freq.keys())[:3]:
                human_col = col.replace("_", " ")
                pairs.append({
                    "instruction": (
                        f"Write a SQL query to get all {entity_plural} "
                        f"where {human_col} is '{val}'."
                    ),
                    "response": f"SELECT * FROM {table_name} WHERE {col} = '{val}';",
                })

    return pairs


# ---------------------------------------------------------------------------
# Policy-based strategy
# ---------------------------------------------------------------------------


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) tuples."""
    pattern = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append((title, body))
    return sections


def _sentence_to_question(sentence: str, topic: str) -> str | None:
    low = sentence.lower()
    if "uptime" in low or "%" in sentence:
        return f"What is the uptime guarantee mentioned in the {topic} policy?"
    if "day" in low and re.search(r"\d+", sentence):
        return f"How many days does the {topic} mention in this context?"
    if "hour" in low:
        return f"What is the response time described in the {topic} policy?"
    if "credit" in low or "refund" in low:
        return f"What does the {topic} say about credits or refunds?"
    return None


def _summarize(text: str, max_chars: int = 400) -> str:
    if len(text) <= max_chars:
        return text.strip()
    truncated = text[:max_chars]
    last_period = truncated.rfind(".")
    if last_period > max_chars // 2:
        return truncated[: last_period + 1].strip()
    return truncated.strip() + "..."


def _policy_pairs(text: str, topic: str) -> list[dict]:
    """Extract Q&A pairs from policy / markdown documents."""
    pairs: list[dict] = []
    sections = _parse_sections(text)

    for title, body in sections:
        if not body.strip():
            continue

        pairs.append({
            "instruction": f"What is the {topic} policy on {title.lower()}?",
            "response": _summarize(body, max_chars=400),
        })

        # Bullet points
        bullets = re.findall(r"[-*•]\s+(.+)", body)
        for bullet in bullets[:4]:
            bullet = bullet.strip()
            if len(bullet) > 20:
                pairs.append({
                    "instruction": (
                        f"In {topic}, what does the following mean: {bullet[:80]}?"
                    ),
                    "response": bullet,
                })

        # Numeric sentences
        sentences = re.split(r"(?<=[.!?])\s+", body)
        for sent in sentences:
            if re.search(r"\d+", sent) and len(sent) > 30:
                question = _sentence_to_question(sent, topic)
                if question:
                    pairs.append({"instruction": question, "response": sent.strip()})

    return pairs
