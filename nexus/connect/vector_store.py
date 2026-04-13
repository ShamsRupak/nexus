"""ChromaDB semantic search connector."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class VectorStoreConnector:
    """Semantic search over ChromaDB collections."""

    def __init__(self, host: str = "localhost", port: int = 8000) -> None:
        self._host = host
        self._port = port
        self._client = None

    def connect(self) -> None:
        try:
            import chromadb

            self._client = chromadb.HttpClient(host=self._host, port=self._port)
            logger.info("ChromaDB connector connected at %s:%d", self._host, self._port)
        except Exception as exc:
            logger.warning("ChromaDB connection failed: %s", exc)

    async def search(
        self,
        collection: str,
        query: str,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError("Connector not connected — call connect() first")
        col = self._client.get_collection(collection)
        results = col.query(query_texts=[query], n_results=n_results)
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        return [{"document": d, "metadata": m} for d, m in zip(docs, metas)]
