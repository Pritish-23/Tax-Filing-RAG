import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# ── config ────────────────────────────────────────────────────────────────────

CHROMA_PATH     = "knowledge_base/chroma_db"
COLLECTION_NAME = "tax_knowledge_base"
EMBED_MODEL     = "all-MiniLM-L6-v2"
TOP_K           = 3

# ── test queries ──────────────────────────────────────────────────────────────
# These are real questions a user would ask the assistant.
# For each one, the top-3 chunks should be clearly relevant.

TEST_QUERIES = [
    {
        "query": "What is the maximum deduction allowed under 80C?",
        "expected_category": "80C",
    },
    {
        "query": "Can I claim 80D deduction for my father's health insurance premium?",
        "expected_category": "80D",
    },
    {
        "query": "How is HRA exemption calculated for someone living in Mumbai?",
        "expected_category": "HRA",
    },
    {
        "query": "What is the standard deduction for salaried employees?",
        "expected_category": "STANDARD_DEDUCTION",
    },
    {
        "query": "What deductions are not allowed under the new tax regime?",
        "expected_category": "NEW_REGIME",
    },
    {
        "query": "Can I switch between old and new tax regime every year?",
        "expected_category": "NEW_REGIME",
    },
    {
        "query": "Is LIC premium eligible for tax deduction?",
        "expected_category": "80C",
    },
    {
        "query": "What is the 80D limit if my parents are senior citizens?",
        "expected_category": "80D",
    },
]

# ── setup ─────────────────────────────────────────────────────────────────────

def get_collection():
    embedding_fn = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    client       = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )

# ── retrieval test ────────────────────────────────────────────────────────────

def run_tests(collection):
    passed = 0
    failed = 0

    for i, test in enumerate(TEST_QUERIES):
        query    = test["query"]
        expected = test["expected_category"]

        results = collection.query(
            query_texts=[query],
            n_results=TOP_K,
        )

        retrieved_categories = [
            m["deduction_category"]
            for m in results["metadatas"][0]
        ]
        retrieved_contents = results["documents"][0]
        distances          = results["distances"][0]

        # Pass if at least 1 of top-3 chunks matches expected category
        match = expected in retrieved_categories
        status = "✓ PASS" if match else "✗ FAIL"
        if match:
            passed += 1
        else:
            failed += 1

        print(f"\n[{i+1}] {status}")
        print(f"  Query    : {query}")
        print(f"  Expected : {expected}")
        print(f"  Got      : {retrieved_categories}")
        print(f"  Distances: {[round(d, 3) for d in distances]}")
        print(f"  Top chunk: {retrieved_contents[0][:200]}...")

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{len(TEST_QUERIES)} passed")
    if failed == 0:
        print("✓ Retrieval sanity check passed. Knowledge base is ready.")
    else:
        print(f"✗ {failed} queries returned wrong category in top-3.")
        print("  Review those chunks — may need better cleaning or chunking.")

# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    collection = get_collection()
    run_tests(collection)