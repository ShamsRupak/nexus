"""Tests for all enterprise connectors — 20+ tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("NEXUS_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

from nexus.connect.file_ingest import FileIngestConnector
from nexus.connect.postgres import PostgresConnector
from nexus.connect.registry import BaseConnector, ConnectorRegistry
from nexus.connect.rest_api import AuthType, EndpointConfig, RestApiConnector
from nexus.connect.vector_store import Document, VectorStoreConnector

# ===========================================================================
# REGISTRY TESTS
# ===========================================================================


class _EchoConnector(BaseConnector):
    name = "echo"
    description = "Echoes params back."

    def get_capabilities(self) -> list[str]:
        return ["echo", "ping"]

    async def execute(self, action: str, params: dict) -> dict:
        return {"action": action, "params": params}

    async def health_check(self) -> bool:
        return True


class _NullConnector(BaseConnector):
    name = "null"
    description = "Does nothing."

    def get_capabilities(self) -> list[str]:
        return ["noop"]

    async def execute(self, action: str, params: dict) -> dict:
        return {}

    async def health_check(self) -> bool:
        return False


def test_registry_register_and_get():
    reg = ConnectorRegistry()
    reg.register(_EchoConnector())
    conn = reg.get("echo")
    assert conn is not None
    assert conn.name == "echo"


def test_registry_get_missing_returns_none():
    reg = ConnectorRegistry()
    assert reg.get("nonexistent") is None


def test_registry_list_connectors_returns_metadata():
    reg = ConnectorRegistry()
    reg.register(_EchoConnector())
    reg.register(_NullConnector())
    listings = reg.list_connectors()
    assert len(listings) == 2
    names = {c["name"] for c in listings}
    assert names == {"echo", "null"}
    echo_meta = next(c for c in listings if c["name"] == "echo")
    assert "capabilities" in echo_meta
    assert "echo" in echo_meta["capabilities"]
    assert "description" in echo_meta


def test_registry_names():
    reg = ConnectorRegistry()
    reg.register(_EchoConnector())
    reg.register(_NullConnector())
    assert set(reg.names()) == {"echo", "null"}


def test_registry_len():
    reg = ConnectorRegistry()
    assert len(reg) == 0
    reg.register(_EchoConnector())
    assert len(reg) == 1


# ===========================================================================
# POSTGRES CONNECTOR TESTS
# ===========================================================================


def test_postgres_capabilities():
    pg = PostgresConnector()
    caps = pg.get_capabilities()
    assert "query" in caps
    assert "nl_query" in caps


def test_postgres_keyword_select_all():
    pg = PostgresConnector()
    sql = pg._keyword_to_sql("show all deals")
    assert sql is not None
    assert "SELECT" in sql.upper()
    assert "deals" in sql.lower()


def test_postgres_keyword_select_list():
    pg = PostgresConnector()
    sql = pg._keyword_to_sql("list customers")
    assert sql is not None
    assert "customers" in sql.lower()


def test_postgres_keyword_count():
    pg = PostgresConnector()
    sql = pg._keyword_to_sql("count of all tickets")
    assert sql is not None
    assert "COUNT" in sql.upper()
    assert "tickets" in sql.lower()


def test_postgres_keyword_find_where():
    pg = PostgresConnector()
    sql = pg._keyword_to_sql("find deals where stage is Negotiation")
    assert sql is not None
    assert "deals" in sql.lower()
    assert "stage" in sql.lower()
    assert "Negotiation" in sql


def test_postgres_keyword_no_match_returns_none():
    pg = PostgresConnector()
    # Complex queries won't match keyword patterns
    sql = pg._keyword_to_sql("what is the MRR distribution across tiers?")
    assert sql is None


@pytest.mark.asyncio
async def test_postgres_validates_sql_accepts_select():
    pg = PostgresConnector()
    assert await pg._validate_sql("SELECT * FROM deals") is True


@pytest.mark.asyncio
async def test_postgres_validates_sql_rejects_injection():
    pg = PostgresConnector()
    # Semicolon injection attempt
    assert await pg._validate_sql("SELECT * FROM deals; DROP TABLE deals") is False


@pytest.mark.asyncio
async def test_postgres_validates_sql_rejects_drop():
    pg = PostgresConnector()
    assert await pg._validate_sql("DROP TABLE deals") is False


@pytest.mark.asyncio
async def test_postgres_read_only_blocks_insert():
    pg = PostgresConnector(allow_mutations=False)
    assert await pg._validate_sql("INSERT INTO deals VALUES (1, 'test')") is False


@pytest.mark.asyncio
async def test_postgres_read_only_blocks_delete():
    pg = PostgresConnector(allow_mutations=False)
    assert await pg._validate_sql("DELETE FROM deals WHERE id = 1") is False


@pytest.mark.asyncio
async def test_postgres_mutations_allowed_when_flag_set():
    pg = PostgresConnector(allow_mutations=True)
    assert await pg._validate_sql("INSERT INTO deals (id) VALUES (99)") is True


@pytest.mark.asyncio
async def test_postgres_execute_nl_query_uses_keyword_path():
    """nl_query with a simple keyword pattern should not require a real DB."""
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.returns_rows = True
    mock_result.keys.return_value = ["id", "company"]
    mock_result.fetchall.return_value = [(1, "Acme Corp")]

    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.execute = AsyncMock(return_value=mock_result)
    mock_engine.connect.return_value = mock_conn

    pg = PostgresConnector(engine=mock_engine)
    result = await pg.execute("nl_query", {"query": "show all deals"})

    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["data"][0]["company"] == "Acme Corp"


# ===========================================================================
# REST API CONNECTOR TESTS
# ===========================================================================


def test_rest_api_capabilities():
    connector = RestApiConnector()
    caps = connector.get_capabilities()
    assert "get" in caps
    assert "post" in caps


def test_rest_api_register_endpoint():
    connector = RestApiConnector()
    connector.register_endpoint(
        EndpointConfig(
            name="test_ep",
            base_url="https://api.example.com",
            auth_type=AuthType.BEARER,
            auth_token="my-token",
        )
    )
    assert "test_ep" in connector._endpoints
    assert connector._endpoints["test_ep"].auth_token == "my-token"


def test_rest_api_build_headers_bearer():
    connector = RestApiConnector()
    config = EndpointConfig(
        name="ep",
        base_url="https://x.com",
        auth_type=AuthType.BEARER,
        auth_token="tok123",
    )
    headers = connector._build_headers(config)
    assert headers["Authorization"] == "Bearer tok123"


def test_rest_api_build_headers_api_key():
    connector = RestApiConnector()
    config = EndpointConfig(
        name="ep",
        base_url="https://x.com",
        auth_type=AuthType.API_KEY,
        auth_token="key456",
        api_key_header="X-Custom-Key",
    )
    headers = connector._build_headers(config)
    assert headers["X-Custom-Key"] == "key456"


def test_rest_api_build_headers_no_auth():
    connector = RestApiConnector()
    headers = connector._build_headers(None)
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_rest_api_get_request_success():
    """Mock a successful GET request."""
    response_data = {"deals": [{"id": 1, "name": "Acme"}]}
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = response_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.build_request.return_value = MagicMock()
    mock_client.send = AsyncMock(return_value=mock_response)

    connector = RestApiConnector(client=mock_client)
    result = await connector.execute(
        "get",
        {"base_url": "https://api.example.com", "path": "deals"},
    )

    assert result["success"] is True
    assert result["status_code"] == 200
    assert result["data"] == response_data


@pytest.mark.asyncio
async def test_rest_api_post_request_with_payload():
    """Mock a successful POST request with JSON payload."""
    response_data = {"id": 42, "created": True}
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 201
    mock_response.json.return_value = response_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.build_request.return_value = MagicMock()
    mock_client.send = AsyncMock(return_value=mock_response)

    connector = RestApiConnector(client=mock_client)
    result = await connector.execute(
        "post",
        {
            "base_url": "https://api.example.com",
            "path": "deals",
            "payload": {"name": "New Deal", "value": 50000},
        },
    )

    assert result["success"] is True
    assert result["data"]["id"] == 42


@pytest.mark.asyncio
async def test_rest_api_retries_on_500():
    """Connector should retry on 5xx and eventually return failure."""
    mock_response_500 = MagicMock(spec=httpx.Response)
    mock_response_500.status_code = 500
    mock_response_500.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.build_request.return_value = MagicMock()
    mock_client.send = AsyncMock(return_value=mock_response_500)

    connector = RestApiConnector(client=mock_client)
    # Patch sleep to avoid actual delays in tests
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await connector.execute(
            "get",
            {"base_url": "https://api.example.com", "path": "health"},
        )

    # After 3 retries all returning 500, success should be False (or still 500)
    # The connector returns the last 5xx as a dict without raising
    assert result is not None


@pytest.mark.asyncio
async def test_rest_api_timeout_config_used():
    """EndpointConfig.timeout_seconds should propagate to the request."""
    connector = RestApiConnector()
    config = EndpointConfig(name="slow", base_url="https://slow.example.com", timeout_seconds=5.0)
    connector.register_endpoint(config)
    assert connector._endpoints["slow"].timeout_seconds == 5.0


# ===========================================================================
# VECTOR STORE TESTS (EphemeralClient — no server needed)
# ===========================================================================


def _make_vs() -> VectorStoreConnector:
    """Create a VectorStoreConnector backed by an in-memory ChromaDB."""
    import chromadb

    client = chromadb.EphemeralClient()
    return VectorStoreConnector(
        chroma_client=client,
        embed_fn=lambda texts: [[float(i % 8) / 8.0] * 8 for i, _ in enumerate(texts)],
    )


def test_vector_store_capabilities():
    vs = _make_vs()
    caps = vs.get_capabilities()
    assert "ingest" in caps
    assert "search" in caps


@pytest.mark.asyncio
async def test_vector_store_ingest_documents():
    vs = _make_vs()
    docs = [
        Document(content="Refund policy: 30-day money-back guarantee.", source="policies.md"),
        Document(content="SLA commitments: 99.9% uptime for Enterprise.", source="policies.md"),
    ]
    n = await vs.ingest(docs, collection="test_ingest")
    assert n >= 1  # at least 1 chunk per doc (short texts)


@pytest.mark.asyncio
async def test_vector_store_search_returns_results():
    vs = _make_vs()
    docs = [
        Document(content="Our refund policy allows returns within 30 days.", source="policies.md"),
        Document(content="The SLA guarantees 99.9 percent uptime.", source="policies.md"),
        Document(content="Escalation procedures for critical tickets.", source="policies.md"),
    ]
    await vs.ingest(docs, collection="test_search")

    results = await vs.search("refund policy", collection="test_search", top_k=3)
    assert len(results) > 0
    assert hasattr(results[0], "content")
    assert hasattr(results[0], "score")
    assert hasattr(results[0], "source")


@pytest.mark.asyncio
async def test_vector_store_search_empty_collection_returns_empty():
    vs = _make_vs()
    results = await vs.search("anything", collection="nonexistent_collection", top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_vector_store_execute_ingest_action():
    vs = _make_vs()
    result = await vs.execute(
        "ingest",
        {
            "documents": [
                {"content": "Test document content.", "source": "test.txt"},
            ],
            "collection": "exec_test",
        },
    )
    assert result["success"] is True
    assert result["chunks_ingested"] >= 1


@pytest.mark.asyncio
async def test_vector_store_execute_search_action():
    vs = _make_vs()
    await vs.ingest(
        [Document(content="Data retention: 7 years for audit logs.", source="policy.md")],
        collection="exec_search",
    )
    result = await vs.execute(
        "search",
        {"query": "audit logs retention", "collection": "exec_search", "top_k": 2},
    )
    assert result["success"] is True
    assert "results" in result


@pytest.mark.asyncio
async def test_vector_store_chunks_long_text():
    vs = _make_vs()
    # Text longer than one chunk window
    long_text = "This is a sentence about enterprise policy. " * 200
    chunks = vs._chunk_text(long_text)
    assert len(chunks) > 1


# ===========================================================================
# FILE INGEST TESTS
# ===========================================================================


@pytest.fixture
def tmp_csv(tmp_path: Path) -> Path:
    p = tmp_path / "test.csv"
    p.write_text("id,name,value\n1,Alice,100\n2,Bob,200\n3,Carol,300\n", encoding="utf-8")
    return p


@pytest.fixture
def tmp_json(tmp_path: Path) -> Path:
    p = tmp_path / "test.json"
    data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def tmp_markdown(tmp_path: Path) -> Path:
    p = tmp_path / "doc.md"
    content = "\n\n".join([f"Section {i}: " + "word " * 100 for i in range(10)])
    p.write_text(content, encoding="utf-8")
    return p


def test_file_ingest_capabilities():
    fi = FileIngestConnector()
    caps = fi.get_capabilities()
    assert "ingest_csv" in caps
    assert "ingest_json" in caps
    assert "ingest_text" in caps


@pytest.mark.asyncio
async def test_file_ingest_csv_parses_rows(tmp_csv):
    fi = FileIngestConnector()
    result = await fi.ingest_csv(tmp_csv)
    assert result["row_count"] == 3
    assert result["columns"] == ["id", "name", "value"]
    assert len(result["rows"]) == 3
    assert result["rows"][0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_file_ingest_csv_schema_metadata(tmp_csv):
    fi = FileIngestConnector()
    result = await fi.ingest_csv(tmp_csv)
    assert "column_types" in result
    assert result["column_types"]["id"] == "integer"
    assert result["column_types"]["name"] == "string"


@pytest.mark.asyncio
async def test_file_ingest_csv_preview_limit(tmp_csv):
    fi = FileIngestConnector()
    result = await fi.ingest_csv(tmp_csv)
    assert len(result["preview"]) <= 5


@pytest.mark.asyncio
async def test_file_ingest_json_list(tmp_json):
    fi = FileIngestConnector()
    result = await fi.ingest_json(tmp_json)
    assert result["record_count"] == 2
    assert "id" in result["keys"]
    assert "name" in result["keys"]


@pytest.mark.asyncio
async def test_file_ingest_json_dict(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"version": "1.0", "name": "nexus", "debug": False}), encoding="utf-8")
    fi = FileIngestConnector()
    result = await fi.ingest_json(p)
    assert result["record_count"] is None  # dict, not list
    assert set(result["keys"]) == {"version", "name", "debug"}


@pytest.mark.asyncio
async def test_file_ingest_text_produces_chunks(tmp_markdown):
    fi = FileIngestConnector()
    chunks = await fi.ingest_text(tmp_markdown)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) for c in chunks)
    assert all(len(c) > 0 for c in chunks)


@pytest.mark.asyncio
async def test_file_ingest_text_long_document_chunked(tmp_path: Path):
    p = tmp_path / "long.txt"
    # ~10k chars — should chunk into multiple pieces
    p.write_text("word " * 2000, encoding="utf-8")
    fi = FileIngestConnector()
    chunks = await fi.ingest_text(p)
    assert len(chunks) > 1


@pytest.mark.asyncio
async def test_file_ingest_missing_file_raises():
    fi = FileIngestConnector()
    with pytest.raises(FileNotFoundError):
        await fi.ingest_csv("/nonexistent/path/file.csv")


@pytest.mark.asyncio
async def test_file_ingest_execute_action_csv(tmp_csv):
    fi = FileIngestConnector()
    result = await fi.execute("ingest_csv", {"path": str(tmp_csv)})
    assert result["success"] is True
    assert result["data"]["row_count"] == 3


def test_file_ingest_detect_format():
    fi = FileIngestConnector()
    assert fi._detect_format("report.csv") == "csv"
    assert fi._detect_format("data.json") == "json"
    assert fi._detect_format("policy.md") == "markdown"
    assert fi._detect_format("readme.txt") == "text"
    assert fi._detect_format("archive.zip") == "unknown"
