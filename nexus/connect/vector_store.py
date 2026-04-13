"""ChromaDB vector store connector with semantic search and document chunking."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from nexus.config import get_settings
from nexus.connect.registry import BaseConnector

logger = logging.getLogger(__name__)

# Chunking parameters
_CHUNK_TOKENS = 512
_OVERLAP_TOKENS = 50
_AVG_CHARS_PER_TOKEN = 4  # approximation used when tiktoken unavailable


@dataclass
class Document:
    content: str
    source: str
    document_type: str = "text"
    page: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    content: str
    score: float
    source: str
    document_type: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


def _default_embed(texts: list[str]) -> list[list[float]]:
    """Hash-based stub embedding — deterministic, no model required."""
    import struct
    result: list[list[float]] = []
    for text in texts:
        h = hashlib.sha256(text.encode()).digest()
        # Unpack 8 floats from 32 bytes → normalise to [-1, 1]
        floats = [struct.unpack("f", h[i : i + 4])[0] for i in range(0, 32, 4)]
        # Normalise
        norm = sum(f * f for f in floats) ** 0.5 or 1.0
        result.append([f / norm for f in floats])
    return result


class VectorStoreConnector(BaseConnector):
    """ChromaDB-backed semantic search with configurable embeddings and chunking."""

    name = "vector_store"
    description = (
        "Ingest and semantically search document collections (policies, wikis, docs) "
        "using ChromaDB and sentence-transformer embeddings."
    )

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
        chroma_client=None,  # Injected for testing (e.g. EphemeralClient)
    ) -> None:
        settings = get_settings()
        self._host = host or settings.chroma_host
        self._port = port or settings.chroma_port
        self._embed_fn = embed_fn  # None → try sentence-transformers, then stub
        self._client = chroma_client
        self._ef = None  # ChromaDB embedding function wrapper

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def get_capabilities(self) -> list[str]:
        return ["ingest", "search", "delete_collection", "list_collections"]

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            client.heartbeat()
            return True
        except Exception:
            return False

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "ingest":
            docs = [Document(**d) if isinstance(d, dict) else d for d in params["documents"]]
            n = await self.ingest(docs, params.get("collection", "default"))
            return {"success": True, "chunks_ingested": n}
        if action == "search":
            results = await self.search(
                query=params["query"],
                collection=params.get("collection", "default"),
                top_k=params.get("top_k", 5),
                filters=params.get("filters"),
            )
            return {"success": True, "results": [_sr_to_dict(r) for r in results]}
        if action == "list_collections":
            client = self._get_client()
            cols = client.list_collections()
            return {"success": True, "collections": [c.name for c in cols]}
        if action == "delete_collection":
            client = self._get_client()
            client.delete_collection(params["collection"])
            return {"success": True}
        raise ValueError(f"Unknown vector_store action: {action!r}")

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    async def ingest(self, documents: list[Document], collection: str = "default") -> int:
        """Chunk, embed, and upsert documents into a collection. Returns chunk count."""
        client = self._get_client()
        col = client.get_or_create_collection(
            name=collection,
            embedding_function=self._get_ef(),
        )

        all_ids: list[str] = []
        all_texts: list[str] = []
        all_metas: list[dict] = []

        for doc in documents:
            chunks = self._chunk_text(doc.content)
            # Include a short content hash so two docs from the same source
            # don't collide when they start at chunk_index 0.
            content_sig = hashlib.md5(doc.content[:64].encode()).hexdigest()[:8]
            for idx, chunk in enumerate(chunks):
                chunk_id = self._chunk_id(f"{doc.source}:{content_sig}", idx)
                meta = {
                    "source": doc.source,
                    "document_type": doc.document_type,
                    "page": doc.page,
                    "chunk_index": idx,
                    "ingested_at": datetime.utcnow().isoformat(),
                    **doc.metadata,
                }
                all_ids.append(chunk_id)
                all_texts.append(chunk)
                all_metas.append(meta)

        if all_texts:
            col.upsert(documents=all_texts, ids=all_ids, metadatas=all_metas)

        logger.info("Ingested %d chunks into collection '%s'", len(all_texts), collection)
        return len(all_texts)

    async def search(
        self,
        query: str,
        collection: str = "default",
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[SearchResult]:
        """Semantic search returning ranked SearchResult objects."""
        client = self._get_client()
        try:
            col = client.get_collection(name=collection, embedding_function=self._get_ef())
        except Exception:
            logger.warning("Collection '%s' not found", collection)
            return []

        where = filters or None
        results = col.query(
            query_texts=[query],
            n_results=min(top_k, col.count() or 1),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        out: list[SearchResult] = []
        for doc, meta, dist in zip(docs, metas, distances):
            # ChromaDB returns L2 distance; convert to cosine-like score (lower dist = higher score)
            score = max(0.0, 1.0 - dist / 2.0)
            out.append(
                SearchResult(
                    content=doc,
                    score=round(score, 4),
                    source=meta.get("source", ""),
                    document_type=meta.get("document_type", "text"),
                    chunk_index=meta.get("chunk_index", 0),
                    metadata=meta,
                )
            )
        return out

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks using tiktoken if available."""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            tokens = enc.encode(text)
            chunks: list[str] = []
            start = 0
            while start < len(tokens):
                end = min(start + _CHUNK_TOKENS, len(tokens))
                chunk_tokens = tokens[start:end]
                chunks.append(enc.decode(chunk_tokens))
                if end == len(tokens):
                    break
                start += _CHUNK_TOKENS - _OVERLAP_TOKENS
            return chunks or [text]
        except Exception:
            # Char-based fallback
            size = _CHUNK_TOKENS * _AVG_CHARS_PER_TOKEN
            overlap = _OVERLAP_TOKENS * _AVG_CHARS_PER_TOKEN
            chunks = []
            start = 0
            while start < len(text):
                end = min(start + size, len(text))
                chunks.append(text[start:end])
                if end == len(text):
                    break
                start += size - overlap
            return chunks or [text]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            import chromadb
            self._client = chromadb.HttpClient(host=self._host, port=self._port)
        return self._client

    def _get_ef(self):
        """Return a ChromaDB-compatible embedding function."""
        if self._ef is not None:
            return self._ef

        embed = self._embed_fn

        if embed is None:
            # Try sentence-transformers
            try:
                from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
                self._ef = SentenceTransformerEmbeddingFunction("all-MiniLM-L6-v2")
                return self._ef
            except Exception:
                pass
            embed = _default_embed

        self._ef = _make_chroma_ef(embed)
        return self._ef

    @staticmethod
    def _chunk_id(source: str, idx: int) -> str:
        return hashlib.md5(f"{source}:{idx}".encode()).hexdigest()


def _make_chroma_ef(embed_fn: Callable[[list[str]], list[list[float]]]):
    """Factory: wraps a plain embedding function in a ChromaDB-compliant class.

    ChromaDB >= 0.4.16 inspects the signature of __call__ and requires the first
    parameter to be named exactly 'self'.  We generate the class at module level so
    there is no closure conflict with an outer 'self'.
    """
    try:
        from chromadb import EmbeddingFunction, Documents, Embeddings

        class _WrappedEF(EmbeddingFunction):
            is_legacy = False

            def name(self) -> str:
                return "nexus_fn_embedder"

            def __call__(self, input: Documents) -> Embeddings:
                return embed_fn(list(input))

        return _WrappedEF()

    except Exception:
        # Older chromadb or import failure — plain callable is fine
        class _PlainEF:
            def __call__(self, input):
                return embed_fn(list(input))

        return _PlainEF()


def _sr_to_dict(r: SearchResult) -> dict:
    return {
        "content": r.content,
        "score": r.score,
        "source": r.source,
        "document_type": r.document_type,
        "chunk_index": r.chunk_index,
        "metadata": r.metadata,
    }
