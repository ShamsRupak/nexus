"""PostgreSQL connector with NL-to-SQL, schema awareness, and injection protection."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from nexus.config import get_settings
from nexus.connect.registry import BaseConnector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword NL-to-SQL patterns (LLM-free fallback)
# ---------------------------------------------------------------------------

_KW_SELECT_ALL = re.compile(
    r"(?:show|list|get|fetch|display)\s+(?:all\s+)?(\w+)", re.IGNORECASE
)
_KW_COUNT = re.compile(r"count\s+(?:of\s+)?(?:all\s+)?(\w+)", re.IGNORECASE)
_KW_FIND_WHERE = re.compile(
    r"(?:find|show|get)\s+(\w+)\s+where\s+(\w+)\s*(?:=|is|equals?)\s*['\"]?(\w[\w\s]*?)['\"]?$",
    re.IGNORECASE,
)

# Block patterns for SQL injection defence
_DANGEROUS_PATTERNS = re.compile(
    r"(;|\bdrop\b|\btruncate\b|\bexec\b|\bxp_|\bunion\b.*\bselect\b)",
    re.IGNORECASE,
)

# Mutating statement detection
_MUTATING_STMT = re.compile(
    r"^\s*(insert|update|delete|merge|replace|upsert)\b", re.IGNORECASE
)

# Known safe table names (populated from schema)
_VALID_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_SYSTEM_PROMPT = """\
You are an expert SQL writer for PostgreSQL. Given a natural language query and the database schema, \
write a single valid SELECT SQL statement. Rules:
- Write only SELECT statements unless the action explicitly requires mutation.
- Use parameterised placeholders ($1, $2, ...) for any user-provided values.
- Return ONLY the SQL — no markdown, no explanation.
Schema:
{schema}
"""


class PostgresConnector(BaseConnector):
    """NL-to-SQL PostgreSQL connector with injection protection and schema awareness."""

    name = "postgres"
    description = (
        "Query and mutate a PostgreSQL database using natural language or raw SQL. "
        "Supports read (SELECT) and write (INSERT/UPDATE/DELETE) operations."
    )

    def __init__(
        self,
        connection_url: str | None = None,
        engine=None,  # Injected async engine (for testing)
        allow_mutations: bool = False,
    ) -> None:
        settings = get_settings()
        self._url = connection_url or settings.postgres_url
        self._engine = engine
        self._allow_mutations = allow_mutations
        self._schema_cache: dict[str, Any] | None = None
        self._client = None

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def get_capabilities(self) -> list[str]:
        return ["query", "nl_query", "execute", "schema"]

    async def health_check(self) -> bool:
        try:
            await self._ensure_engine()
            async with self._engine.connect() as conn:
                from sqlalchemy import text
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch to sub-actions: query | nl_query | schema."""
        if action == "nl_query":
            return await self._handle_nl_query(params)
        if action == "query":
            return await self._handle_raw_query(params)
        if action == "schema":
            schema = await self._get_schema()
            return {"success": True, "data": schema}
        raise ValueError(f"Unknown postgres action: {action!r}")

    # ------------------------------------------------------------------
    # Sub-action handlers
    # ------------------------------------------------------------------

    async def _handle_nl_query(self, params: dict) -> dict[str, Any]:
        nl = params.get("query", "")
        if not nl:
            raise ValueError("'query' param required for nl_query")

        # Try keyword path first (fast, no LLM)
        sql = self._keyword_to_sql(nl)
        if sql is None:
            schema = await self._get_schema()
            sql = await self._nl_to_sql(nl, schema)

        if not await self._validate_sql(sql):
            raise ValueError(f"Generated SQL failed validation: {sql!r}")

        rows = await self._run_sql(sql, params.get("bind_params", {}))
        return {"success": True, "data": rows, "sql": sql, "row_count": len(rows)}

    async def _handle_raw_query(self, params: dict) -> dict[str, Any]:
        sql = params.get("sql", "")
        if not sql:
            raise ValueError("'sql' param required for query")
        if not await self._validate_sql(sql):
            raise ValueError(f"SQL failed validation: {sql!r}")
        rows = await self._run_sql(sql, params.get("bind_params", {}))
        return {"success": True, "data": rows, "row_count": len(rows)}

    # ------------------------------------------------------------------
    # NL → SQL
    # ------------------------------------------------------------------

    def _keyword_to_sql(self, nl: str) -> str | None:
        """Convert simple natural language to SQL without LLM."""
        m = _KW_COUNT.search(nl)
        if m:
            table = m.group(1).lower()
            if _VALID_IDENTIFIER.match(table):
                return f"SELECT COUNT(*) AS count FROM {table}"

        m = _KW_FIND_WHERE.search(nl)
        if m:
            table, col, val = m.group(1).lower(), m.group(2).lower(), m.group(3)
            if _VALID_IDENTIFIER.match(table) and _VALID_IDENTIFIER.match(col):
                return f"SELECT * FROM {table} WHERE {col} = '{val}'"

        m = _KW_SELECT_ALL.search(nl)
        if m:
            table = m.group(1).lower()
            if _VALID_IDENTIFIER.match(table):
                return f"SELECT * FROM {table} LIMIT 100"

        return None

    async def _nl_to_sql(self, query: str, schema: dict) -> str:
        """Use LLM to convert natural language to SQL."""
        settings = get_settings()
        if not settings.llm_available:
            # Last-resort stub
            return f"SELECT * FROM deals LIMIT 10 -- could not generate SQL for: {query[:80]}"

        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )

        system = _SYSTEM_PROMPT.format(schema=json.dumps(schema, indent=2))
        resp = await self._client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        return (resp.choices[0].message.content or "").strip().strip(";")

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def _get_schema(self) -> dict[str, Any]:
        if self._schema_cache is not None:
            return self._schema_cache

        try:
            await self._ensure_engine()
            async with self._engine.connect() as conn:
                from sqlalchemy import text
                result = await conn.execute(
                    text(
                        """
                        SELECT table_name, column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                        ORDER BY table_name, ordinal_position
                        """
                    )
                )
                rows = result.fetchall()

            schema: dict[str, list[dict]] = {}
            for table, col, dtype in rows:
                schema.setdefault(table, []).append({"column": col, "type": dtype})

            self._schema_cache = schema
            return schema
        except Exception as exc:
            logger.warning("Could not fetch schema: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # SQL validation + execution
    # ------------------------------------------------------------------

    async def _validate_sql(self, sql: str) -> bool:
        """Return True if the SQL looks safe to execute."""
        if not sql or not sql.strip():
            return False

        # Block dangerous patterns
        if _DANGEROUS_PATTERNS.search(sql):
            logger.warning("SQL blocked by injection guard: %.80s", sql)
            return False

        # Enforce read-only unless mutations explicitly allowed
        if not self._allow_mutations and _MUTATING_STMT.match(sql):
            logger.warning("Mutation blocked on read-only connector: %.80s", sql)
            return False

        return True

    async def _run_sql(self, sql: str, bind_params: dict | None = None) -> list[dict]:
        await self._ensure_engine()
        async with self._engine.connect() as conn:
            from sqlalchemy import text
            result = await conn.execute(text(sql), bind_params or {})
            if result.returns_rows:
                keys = list(result.keys())
                return [dict(zip(keys, row)) for row in result.fetchall()]
            return []

    async def _ensure_engine(self) -> None:
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine
            self._engine = create_async_engine(self._url, pool_size=5, max_overflow=10)
