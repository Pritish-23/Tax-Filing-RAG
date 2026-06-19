import os
import re
import json
import yaml
from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── config ────────────────────────────────────────────────────────────────────

MANIFEST_PATH  = Path("raw_sources/manifest.json")
CONSTANTS_PATH = Path("data/tax_constants.yaml")
OUTPUT_PATH    = Path("data/chunks.json")

# Chunk size tuned for tax law: large enough to hold a full sub-clause,
# small enough to stay focused on one idea.
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 100

# ── load manifest ─────────────────────────────────────────────────────────────

def load_manifest():
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)

# ── structure-aware splitter ──────────────────────────────────────────────────

def make_splitter():
    """
    RecursiveCharacterTextSplitter with tax-law-aware separators.
    Order of priority:
      1. Double newline (paragraph boundary) — most natural split point
      2. Single newline
      3. Period followed by space — sentence boundary
      4. Comma — last resort within a long sentence
    This order means we never split inside a clause if we can split between paragraphs first.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", ", "],
        length_function=len,
    )

# ── metadata builder ──────────────────────────────────────────────────────────

def build_metadata(source: dict) -> dict:
    """
    Every chunk carries this metadata so ChromaDB can filter by
    AY, deduction category, or document type at retrieval time.
    """
    return {
        "source_id":          source["id"],
        "section":            source["section"],
        "deduction_category": source["deduction_category"],
        "document_type":      source["document_type"],
        "title":              source["title"],
        "effective_from_ay":  source["effective_from_ay"],
        "effective_to_ay":    source["effective_to_ay"],
        "local_path":         source["local_path"],
    }

# ── cleaning ──────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    lines = text.split("\n")
    cleaned = []

    # Patterns to drop entirely
    noise_patterns = [
        r"^(Home|Tax|ITR|GST|TDS|Invest|CA|Business)(\s*[›>].*)?$",
        r"^(Clear offers|ClearTax|Efiling Income Tax|You can efile|Download Black).*",
        r"^(Last updated|Updated on|Published on).*",
        r"^\d+\s*min read$",
        r"^(Share this article|Facebook|Twitter|LinkedIn|WhatsApp)$",
        r"^Table of Contents$",
        r"^\[.*\]$",
        r"^G1-G9 filing.*",
        r"^Elevate processes.*",
        r"^Streamline vendor.*",
        r"^Optimise ITC.*",
        r"^Bulk invoicing.*",
        r"^e-TDS return.*",
        r"^Maximise EBITDA.*",
        r"^Instant working capital.*",
        r"^Automated secretarial.*",
        r"^Connected finance.*",
        r"^Complete supply chain.*",
        r"^File your taxes in.*",
        r"^ITR filed by.*",
        r"^File your ITR.*",
        r"^(Office Address|Privacy Policy|Terms of use|ISO 27001|Data Center|SSL Certified|128-bit).*",
        r"^(CAs, experts and businesses can get GST).*",
        r"^(Our GST Software|Our Goods|Clear can also).*",
        r"^Save taxes with Clear.*",
        r"^Also Read\s*[-–].*",
        r"^\s*[›>]\s*$",
        r"^GST and direct tax compliance$",
        r"^Income Tax$",
        r"^\d{2}C-\d{2}-.*$",       # breadcrumb like "80C-80-Deductions"
        r"^Section \d+.*of Income Tax Act - .*Deduction List$",  # page title duplication
        r"^\|$",
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append("")
            continue
        skip = any(re.match(p, stripped, re.IGNORECASE) for p in noise_patterns)
        if not skip:
            cleaned.append(stripped)

    # Collapse 3+ blank lines into 2
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# ── main chunker ──────────────────────────────────────────────────────────────

def chunk_source(source: dict, splitter) -> list[Document]:
    local_path = Path(source["local_path"])
    if not local_path.exists():
        print(f"  MISSING: {local_path} — skipping")
        return []

    raw_text = local_path.read_text(encoding="utf-8")
    cleaned  = clean_text(raw_text)
    metadata = build_metadata(source)

    # Split into chunks
    chunks = splitter.create_documents(
        texts=[cleaned],
        metadatas=[metadata]
    )

    # Add chunk index to metadata for traceability
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = i
        chunk.metadata["total_chunks"] = len(chunks)

    print(f"  {source['id']}: {len(chunks)} chunks from {len(cleaned)} chars")
    return chunks

# ── serialise for inspection ──────────────────────────────────────────────────

def serialise_chunks(all_chunks: list[Document]) -> list[dict]:
    return [
        {
            "content":  chunk.page_content,
            "metadata": chunk.metadata,
        }
        for chunk in all_chunks
    ]

# ── entry point ───────────────────────────────────────────────────────────────

def main():
    manifest = load_manifest()
    splitter = make_splitter()

    all_chunks = []
    for source in manifest["sources"]:
        chunks = chunk_source(source, splitter)
        all_chunks.extend(chunks)

    print(f"\nTotal chunks: {len(all_chunks)}")

    # Save to data/chunks.json for inspection before ingestion
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(serialise_chunks(all_chunks), f, indent=2, ensure_ascii=False)

    print(f"Saved → {OUTPUT_PATH}")
    print("\nSample chunk (first one):")
    print("-" * 60)
    if all_chunks:
        print(all_chunks[0].page_content[:400])
        print("...")
        print("Metadata:", all_chunks[0].metadata)

if __name__ == "__main__":
    main()