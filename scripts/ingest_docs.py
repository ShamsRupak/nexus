#!/usr/bin/env python3
"""Ingest sample documents into ChromaDB."""

import asyncio
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "sample"


async def ingest() -> None:
    import chromadb

    from nexus.connect.vector_store import Document, VectorStoreConnector

    client = chromadb.HttpClient(host="localhost", port=8001)
    connector = VectorStoreConnector(chroma_client=client)

    all_files = list(DATA_DIR.glob("*.md")) + list(DATA_DIR.glob("*.txt"))
    total_chunks = 0
    collection = "policies"

    for doc_path in all_files:
        text = doc_path.read_text(encoding="utf-8")
        doc = Document(
            content=text,
            source=doc_path.name,
            document_type="markdown" if doc_path.suffix == ".md" else "text",
        )
        n = await connector.ingest([doc], collection=collection)
        total_chunks += n
        print(f"Ingested {n} chunks from {doc_path.name}")

    print(f"\nIngested {total_chunks} chunks into collection '{collection}'")


if __name__ == "__main__":
    asyncio.run(ingest())
