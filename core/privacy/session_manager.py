import uuid
import time
import threading
import logging
from datetime import datetime
from typing import Optional

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from schemas import ExtractedFinancials

# ── config ────────────────────────────────────────────────────────────────────

EMBED_MODEL          = "all-MiniLM-L6-v2"
SESSION_TTL_SECONDS  = 20 * 60   # 20 minutes inactivity
SWEEP_INTERVAL       = 2  * 60   # sweep every 2 minutes

# ── logging (structural only — never log financial values) ────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── session store ─────────────────────────────────────────────────────────────

class SessionStore:
    """
    In-memory store for all active user sessions.
    Each session holds:
      - extracted_financials: the Pydantic model from Phase 3 extraction
      - chroma_collection:    an EphemeralClient ChromaDB collection (in-memory only)
      - created_at:           timestamp of session creation
      - last_active_at:       timestamp of last interaction (used for TTL sweep)

    Nothing in this store is ever written to disk or logged.
    """

    def __init__(self):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL
        )
        self._start_ttl_sweep()
        logger.info("SessionStore initialised — TTL sweep active (every %ds)", SWEEP_INTERVAL)

    # ── session lifecycle ─────────────────────────────────────────────────────

    def create_session(self, financials: ExtractedFinancials) -> str:
        """
        Creates a new session for a user.
        - Generates a UUID session ID
        - Creates an ephemeral ChromaDB collection
        - Embeds the user's financial summary into the collection
        - Stores everything in-memory only
        Returns the session_id the caller should hold onto.
        """
        session_id = str(uuid.uuid4())

        # Each session gets its own EphemeralClient — destroyed when session ends
        client     = chromadb.EphemeralClient()
        collection = client.create_collection(
            name=f"session_{session_id[:8]}",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"}
        )

        # Embed the financial summary as a single searchable document
        # This lets Phase 5 retrieve "user context" alongside tax law chunks
        summary_text = self._build_financial_summary(financials)
        collection.add(
            ids=["financial_summary"],
            documents=[summary_text],
            metadatas=[{
                "type":           "user_financial_summary",
                "session_id":     session_id[:8],   # only prefix logged, never full
                "assessment_year": financials.form16.assessment_year,
            }]
        )

        now = time.time()
        with self._lock:
            self._sessions[session_id] = {
                "financials":   financials,
                "collection":   collection,
                "client":       client,
                "created_at":   now,
                "last_active":  now,
            }

        logger.info(
            "Session created | id_prefix=%s | ay=%s",
            session_id[:8],
            financials.form16.assessment_year
        )
        return session_id

    def get_session(self, session_id: str) -> Optional[dict]:
        """
        Returns session data and updates last_active timestamp.
        Returns None if session does not exist or has expired.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session["last_active"] = time.time()
            return session

    def get_financials(self, session_id: str) -> Optional[ExtractedFinancials]:
        session = self.get_session(session_id)
        return session["financials"] if session else None

    def get_collection(self, session_id: str):
        session = self.get_session(session_id)
        return session["collection"] if session else None

    def delete_session(self, session_id: str) -> bool:
        """
        Immediately destroys all session data.
        Called by the 'Delete my data now' button (Phase 8).
        """
        with self._lock:
            session = self._sessions.pop(session_id, None)

        if session is None:
            logger.warning("delete_session called on non-existent session | id_prefix=%s", session_id[:8])
            return False

        # Explicitly reset the ephemeral client — signals destruction
        try:
            session["client"].reset()
        except Exception:
            pass  # EphemeralClient may already be cleaned up

        logger.info("Session deleted (explicit) | id_prefix=%s", session_id[:8])
        return True

    def session_exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    def active_session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # ── TTL sweep ─────────────────────────────────────────────────────────────

    def _start_ttl_sweep(self):
        """Starts a background daemon thread that sweeps expired sessions."""
        thread = threading.Thread(target=self._sweep_loop, daemon=True)
        thread.start()

    def _sweep_loop(self):
        while True:
            time.sleep(SWEEP_INTERVAL)
            self._sweep_expired()

    def _sweep_expired(self):
        now     = time.time()
        expired = []

        with self._lock:
            for session_id, session in self._sessions.items():
                idle_seconds = now - session["last_active"]
                if idle_seconds > SESSION_TTL_SECONDS:
                    expired.append(session_id)

        for session_id in expired:
            with self._lock:
                session = self._sessions.pop(session_id, None)
            if session:
                try:
                    session["client"].reset()
                except Exception:
                    pass
                logger.info(
                    "Session expired (TTL sweep) | id_prefix=%s",
                    session_id[:8]
                )

        if expired:
            logger.info("TTL sweep complete | expired=%d | remaining=%d",
                        len(expired), self.active_session_count())

    # ── financial summary builder ─────────────────────────────────────────────

    def _build_financial_summary(self, f: ExtractedFinancials) -> str:
        """
        Converts ExtractedFinancials into a plain-text summary that gets
        embedded into the ephemeral collection. Phase 5 retrieves this
        alongside tax law chunks to give the LLM user-specific context.

        Note: this text is embedded in-memory only, never written to disk or logs.
        """
        form16 = f.form16
        inv    = f.investments

        lines = [
            f"Assessment Year: {form16.assessment_year}",
            f"Employer: {form16.employer_name}",
            f"Gross Salary: Rs. {form16.gross_salary:,}",
            f"Basic Salary: Rs. {form16.basic_salary:,}",
            f"HRA Received: Rs. {form16.hra_received:,}",
            f"HRA Exemption Claimed: Rs. {form16.hra_exemption_claimed:,}",
            f"Standard Deduction: Rs. {form16.standard_deduction:,}",
            f"Section 80C Claimed (Form 16): Rs. {form16.deduction_80C_claimed:,}",
            f"Section 80D Claimed (Form 16): Rs. {form16.deduction_80D_claimed:,}",
            f"Net Taxable Income: Rs. {form16.net_taxable_income:,}",
            f"TDS Deducted: Rs. {form16.tds_deducted:,}",
            "",
            "Investment details from bank statement:",
            f"  LIC Premium paid: Rs. {inv.total_lic_premium:,}",
            f"  PPF Deposit: Rs. {inv.total_ppf_deposit:,}",
            f"  ELSS Investment: Rs. {inv.total_elss_investment:,}",
            f"  Total 80C (raw): Rs. {inv.total_80C_raw:,}",
            f"  Self health insurance premium: Rs. {inv.total_self_health_premium:,}",
            f"  Parents health insurance premium: Rs. {inv.total_parents_health_premium:,}",
            f"  Total rent paid (annual): Rs. {inv.total_rent_paid_annual:,}",
        ]

        return "\n".join(lines)


# ── singleton instance ────────────────────────────────────────────────────────
# One store shared across the entire FastAPI app in Phase 8.

store = SessionStore()