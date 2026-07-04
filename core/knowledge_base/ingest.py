import json
import os
from pathlib import Path
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# ── config ────────────────────────────────────────────────────────────────────

CHUNKS_PATH    = Path("data/chunks.json")
CHROMA_PATH    = Path("knowledge_base/chroma_db")
COLLECTION_NAME = "tax_knowledge_base"
EMBED_MODEL    = "all-MiniLM-L6-v2"

# ── setup ─────────────────────────────────────────────────────────────────────

def get_collection():
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)

    embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name=EMBED_MODEL
    )

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))

    # get_or_create so re-running is safe
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"}  # cosine similarity for semantic search
    )
    return collection

# ── ingest ────────────────────────────────────────────────────────────────────

def ingest(collection, chunks: list[dict]):
    # Check what's already in the collection (idempotency)
    existing = set(collection.get()["ids"])
    print(f"Existing documents in collection: {len(existing)}")

    ids, documents, metadatas = [], [], []

    for chunk in chunks:
        # Build a stable unique ID from source + chunk index
        chunk_id = f"{chunk['metadata']['source_id']}_chunk_{chunk['metadata']['chunk_index']}"

        if chunk_id in existing:
            continue  # skip already ingested chunks

        ids.append(chunk_id)
        documents.append(chunk["content"])
        metadatas.append({
            k: str(v) for k, v in chunk["metadata"].items()
        })

    if not ids:
        print("Nothing new to ingest — collection is up to date.")
        return

    # Ingest in batches of 50 to avoid memory spikes
    batch_size = 50
    total = len(ids)
    print(f"Ingesting {total} new chunks in batches of {batch_size}...")

    for i in range(0, total, batch_size):
        batch_ids   = ids[i:i+batch_size]
        batch_docs  = documents[i:i+batch_size]
        batch_metas = metadatas[i:i+batch_size]

        collection.add(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_metas,
        )
        print(f"  ingested batch {i//batch_size + 1} ({min(i+batch_size, total)}/{total})")

    print(f"\n✓ Ingestion complete. Total in collection: {collection.count()}")

# ── entry point ───────────────────────────────────────────────────────────────

def main():
    print(f"Loading chunks from {CHUNKS_PATH}...")
    with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    print(f"Loaded {len(chunks)} chunks")

    print(f"\nConnecting to ChromaDB at {CHROMA_PATH}...")
    collection = get_collection()

    ingest(collection, chunks)

if __name__ == "__main__":
    main()