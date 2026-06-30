import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import anthropic
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langsmith_tracer import tracer

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from deduction_engine import FullTaxAnalysis, build_llm_context

# ── config ────────────────────────────────────────────────────────────────────

CHROMA_PATH      = Path("knowledge_base/chroma_db")
COLLECTION_NAME  = "tax_knowledge_base"
EMBED_MODEL      = "all-MiniLM-L6-v2"
CLAUDE_MODEL     = "claude-haiku-4-5-20251001"   # fast and cost-effective for Q&A
TOP_K_KB         = 3   # chunks from persistent knowledge base
TOP_K_SESSION    = 1   # chunks from ephemeral session collection

# ── clients ───────────────────────────────────────────────────────────────────

_anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

_embedding_fn = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)

def _get_kb_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedding_fn,
    )

# ── retrieval ─────────────────────────────────────────────────────────────────

def retrieve_tax_law(query: str, ay: str, deduction_category: str = None) -> list[str]:
    """
    Retrieves relevant tax law chunks from the persistent knowledge base.
    Filters by deduction_category when provided to improve retrieval precision.
    AY filtering skipped — all chunks cover AY 2025-26 and 2026-27.
    """
    collection = _get_kb_collection()

    if deduction_category:
        where_filter = {"deduction_category": {"$eq": deduction_category}}
    else:
        where_filter = None

    query_kwargs = {
        "query_texts": [query],
        "n_results":   TOP_K_KB,
    }
    if where_filter:
        query_kwargs["where"] = where_filter

    results = collection.query(**query_kwargs)
    return results["documents"][0]


def retrieve_user_context(query: str, session_collection) -> list[str]:
    """
    Retrieves user-specific financial context from the ephemeral session collection.
    """
    if session_collection is None:
        return []
    results = session_collection.query(
        query_texts=[query],
        n_results=TOP_K_SESSION,
    )
    return results["documents"][0]


# ── prompt builder ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a helpful Indian income tax assistant specializing in tax filing for salaried individuals.

Your role:
- Answer questions about tax deductions (80C, 80D, HRA, standard deduction) clearly and accurately
- Explain regime comparison results in plain language
- Always base your answers on the provided tax law context and the user's specific financial data
- Never perform tax arithmetic yourself — use only the pre-computed numbers provided in the context
- If a question is outside your scope (capital gains, business income, NRI taxation), say so clearly
- Keep answers concise, friendly, and jargon-free where possible
- Always mention the Assessment Year your answer applies to

Important: You are not a registered tax advisor. Always recommend the user consult a CA for complex situations."""


def build_prompt(
    query:            str,
    tax_law_chunks:   list[str],
    user_context:     list[str],
    analysis_context: str,
) -> str:
    law_text  = "\n\n---\n\n".join(tax_law_chunks) if tax_law_chunks else "No specific tax law retrieved."
    user_text = "\n\n".join(user_context) if user_context else "No user financial data available."

    return f"""Here is the relevant tax law context:

{law_text}

Here is the user's financial data:

{user_text}

Here is the pre-computed tax analysis (DO NOT recompute these numbers):

{analysis_context}

User's question: {query}

Please answer the question based on the above context. Be specific to the user's situation where relevant."""


# ── main Q&A function ─────────────────────────────────────────────────────────

def answer_question(
    query:              str,
    analysis:           FullTaxAnalysis,
    session_collection,
    deduction_category: str = None,
) -> str:
    import time
    ay             = analysis.deduction_detail.assessment_year
    session_prefix = analysis.session_id[:8]

    # Retrieval with tracing
    t0             = time.time()
    tax_law_chunks = retrieve_tax_law(query, ay, deduction_category)
    retrieval_ms   = (time.time() - t0) * 1000

    tracer.trace_retrieval(
        query=query,
        retrieved_count=len(tax_law_chunks),
        deduction_category=deduction_category,
        session_id_prefix=session_prefix,
        latency_ms=retrieval_ms,
    )

    user_context = retrieve_user_context(query, session_collection)
    analysis_ctx = build_llm_context(analysis)
    prompt       = build_prompt(query, tax_law_chunks, user_context, analysis_ctx)

    # LLM call with tracing
    t0 = time.time()
    response = _anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    llm_ms      = (time.time() - t0) * 1000
    answer_text = response.content[0].text
    token_count = response.usage.input_tokens + response.usage.output_tokens

    tracer.trace_llm_call(
        run_name=f"tax_qa_{deduction_category or 'general'}",
        inputs={
            "query":  query,
            "prompt": prompt,
        },
        outputs={"answer": answer_text},
        latency_ms=llm_ms,
        token_count=token_count,
        session_id_prefix=session_prefix,
        assessment_year=ay,
    )

    return answer_text


# ── regime comparison explainer ───────────────────────────────────────────────

def explain_regime_comparison(
    analysis:           FullTaxAnalysis,
    session_collection,
) -> str:
    """
    Generates a plain-language regime comparison summary.
    Called when the user first uploads documents or requests the comparison view.
    """
    query = "Should I choose old or new tax regime? What are the differences?"
    return answer_question(
        query=query,
        analysis=analysis,
        session_collection=session_collection,
        deduction_category="NEW_REGIME",
    )