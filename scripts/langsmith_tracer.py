import os
import re
import time
import logging
from typing import Any
from dotenv import load_dotenv
from langsmith import Client
from langsmith.run_helpers import traceable

load_dotenv()

logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────

LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "tax-filing-rag")

# ── redaction patterns ────────────────────────────────────────────────────────
# These patterns match financial values in the LLM context block
# and replace them with [REDACTED] before the trace is sent to LangSmith.

REDACTION_PATTERNS = [
    # Monetary amounts: "Rs. 1,50,000" or "Rs. 150000"
    (r"Rs\.\s*[\d,]+", "[REDACTED_AMOUNT]"),
    # Standalone large numbers (salary/tax figures)
    (r"\b\d{4,}[\d,]*\b", "[REDACTED_NUMBER]"),
    # PAN patterns: 5 letters + 4 digits + 1 letter
    (r"\b[A-Z]{5}\d{4}[A-Z]\b", "[REDACTED_PAN]"),
    # TAN patterns
    (r"\b[A-Z]{4}\d{5}[A-Z]\b", "[REDACTED_TAN]"),
    # Employee/employer names after known labels
    (r"(Employee:\s*)([^\n]+)", r"\1[REDACTED_NAME]"),
    (r"(Employer:\s*)([^\n]+)", r"\1[REDACTED_NAME]"),
]

# Fields that are safe to log (structural metadata only)
SAFE_FIELDS = {
    "assessment_year",
    "deduction_category",
    "session_id_prefix",
    "model",
    "latency_ms",
    "tokens_used",
    "extraction_confidence",
    "fields_extracted",
    "regime_recommended",
    "error",
}

# ── redactor ──────────────────────────────────────────────────────────────────

def redact_text(text: str) -> str:
    """
    Strips financial values from any string before it gets logged.
    Preserves structural information (field names, section labels)
    while removing actual monetary amounts and personal identifiers.
    """
    if not text or not isinstance(text, str):
        return text
    for pattern, replacement in REDACTION_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def redact_dict(data: dict) -> dict:
    """
    Recursively redacts a dictionary, applying redaction only to
    string values that are not in the safe fields list.
    """
    redacted = {}
    for key, value in data.items():
        if key in SAFE_FIELDS:
            redacted[key] = value
        elif isinstance(value, str):
            redacted[key] = redact_text(value)
        elif isinstance(value, dict):
            redacted[key] = redact_dict(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_text(v) if isinstance(v, str)
                else redact_dict(v) if isinstance(v, dict)
                else v
                for v in value
            ]
        else:
            redacted[key] = value
    return redacted


# ── LangSmith client ──────────────────────────────────────────────────────────

def get_langsmith_client() -> Client | None:
    if not LANGSMITH_API_KEY:
        logger.warning("LANGSMITH_API_KEY not set — tracing disabled")
        return None
    try:
        client = Client(api_key=LANGSMITH_API_KEY)
        return client
    except Exception as e:
        logger.warning(f"LangSmith client init failed: {e} — tracing disabled")
        return None


# ── trace logger ──────────────────────────────────────────────────────────────

class TaxRAGTracer:
    """
    Wraps LangSmith tracing with automatic redaction of financial values.
    Used in rag_engine.py to trace each Claude API call without leaking PII.
    """

    def __init__(self):
        self.client  = get_langsmith_client()
        self.project = LANGSMITH_PROJECT
        self.enabled = self.client is not None
        if self.enabled:
            logger.info("LangSmith tracing enabled | project=%s", self.project)
        else:
            logger.info("LangSmith tracing disabled")

    def trace_llm_call(
        self,
        run_name:          str,
        inputs:            dict,
        outputs:           dict,
        latency_ms:        float,
        token_count:       int,
        session_id_prefix: str,
        assessment_year:   str,
        error:             str = None,
    ):
        """
        Logs a single LLM call to LangSmith with financial values redacted.
        Only structural metadata and redacted prompts are sent.
        """
        if not self.enabled:
            return

        # Redact inputs and outputs before sending
        safe_inputs  = redact_dict(inputs)
        safe_outputs = redact_dict(outputs)

        metadata = {
            "session_id_prefix": session_id_prefix,
            "assessment_year":   assessment_year,
            "latency_ms":        latency_ms,
            "token_count":       token_count,
            "project":           self.project,
        }
        if error:
            metadata["error"] = error

        try:
            run = self.client.create_run(
                project_name=self.project,
                name=run_name,
                run_type="llm",
                inputs=safe_inputs,
                outputs=safe_outputs,
                extra={"metadata": metadata},
                error=error,
            )
            logger.info(
                "Traced LLM call | run=%s | latency=%.0fms | tokens=%d | ay=%s",
                run_name, latency_ms, token_count, assessment_year
            )
        except Exception as e:
            # Tracing failure must never break the main application flow
            logger.warning("LangSmith trace failed (non-fatal): %s", e)

    def trace_retrieval(
        self,
        query:             str,
        retrieved_count:   int,
        deduction_category: str,
        session_id_prefix: str,
        latency_ms:        float,
    ):
        """
        Logs a retrieval call — query is redacted, counts and categories are safe.
        """
        if not self.enabled:
            return

        try:
            self.client.create_run(
                project_name=self.project,
                name="retrieve_tax_law",
                run_type="retriever",
                inputs={"query": redact_text(query)},
                outputs={"retrieved_count": retrieved_count},
                extra={"metadata": {
                    "deduction_category":  deduction_category or "none",
                    "session_id_prefix":   session_id_prefix,
                    "latency_ms":          latency_ms,
                }},
            )
        except Exception as e:
            logger.warning("LangSmith retrieval trace failed (non-fatal): %s", e)


# ── singleton ─────────────────────────────────────────────────────────────────

tracer = TaxRAGTracer()