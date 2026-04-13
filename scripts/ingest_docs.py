#!/usr/bin/env python3
"""Ingest sample documents into ChromaDB."""

from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "sample"


def ingest():
    import chromadb

    client = chromadb.HttpClient(host="localhost", port=8001)
    collection = client.get_or_create_collection("nexus_docs")

    docs = list(DATA_DIR.glob("*.md")) + list(DATA_DIR.glob("*.txt"))
    for i, doc_path in enumerate(docs):
        text = doc_path.read_text(encoding="utf-8")
        # Chunk into paragraphs
        chunks = [p.strip() for p in text.split("\n\n") if p.strip()]
        for j, chunk in enumerate(chunks):
            collection.upsert(
                documents=[chunk],
                ids=[f"{doc_path.stem}_{j}"],
                metadatas=[{"source": doc_path.name, "chunk": j}],
            )
        print(f"Ingested {len(chunks)} chunks from {doc_path.name}")


if __name__ == "__main__":
    ingest()
