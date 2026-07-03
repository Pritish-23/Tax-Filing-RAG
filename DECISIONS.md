# Architecture Decision Record

Key design decisions made during the Tax Filing RAG Assistant project,
with the reasoning and trade-offs behind each one.

---

## 1. Ephemeral ChromaDB over a persistent database with row deletion

**Decision:** Use ChromaDB's `EphemeralClient` (in-memory only) for user
session data rather than a persistent store with a delete-on-logout mechanism.

**Why not persistent + delete?**
A persistent store with row deletion has two failure modes that matter for
financial data. First, deletion is not guaranteed to be immediate or complete
— most databases use soft deletes, write-ahead logs, or backup snapshots that
retain deleted data beyond the application layer. Second, a bug in the deletion
logic silently retains data the user believes is gone. Both failure modes are
invisible to the user and difficult to audit.

**Why ephemeral?**
An in-memory collection is physically incapable of persisting beyond the
process lifetime. There is no code path, no matter how buggy, that can write
session data to disk. The privacy guarantee is enforced by the runtime, not
by application logic. This is a stronger guarantee than "we delete it, trust
us."

**Trade-off accepted:**
If the FastAPI process restarts (e.g. a Railway redeploy), all active sessions
are lost and users must re-upload. For a portfolio demo this is acceptable.
In production this would require a distributed session store with proper
TTL-based eviction (e.g. Redis with key expiry), which gives similar
guarantees with restart resilience.

---

## 2. Deterministic Python for tax math, not LLM arithmetic

**Decision:** All tax liability computation (slab rates, surcharge, cess,
rebate 87A, HRA Rule 2A exemption) is implemented in pure Python. The LLM
never performs arithmetic.

**Why not let the LLM compute?**
LLMs are unreliable at multi-step arithmetic, especially with Indian tax
rules which involve sequential dependencies (compute base tax → apply rebate
→ apply surcharge on post-rebate amount → apply cess on post-surcharge
amount). A 1% error on a ₹50L income scenario is a ₹50,000 mistake. The
eval harness confirmed 100% accuracy on regime recommendations precisely
because the math is deterministic — no prompt engineering can match that
guarantee.

**What the LLM actually does:**
Explains the pre-computed results in plain language, maps deductions to
their legal sections, and answers follow-up questions. This is where LLMs
are genuinely strong — synthesis and explanation, not arithmetic.

**Trade-off accepted:**
Tax constants (slab rates, limits) are hardcoded in `tax_constants.yaml`
and require a manual update when the Finance Bill changes. This is
intentional — a human should verify new slab rates before they go into
a tax computation tool.

---

## 3. Year-agnostic architecture via `tax_constants.yaml`

**Decision:** All numeric constants (slab boundaries, deduction limits,
rebate thresholds) are stored in a versioned YAML file keyed by assessment
year, not embedded in code or in knowledge base text chunks.

**Why not hardcode constants in code?**
Tax rules change every Budget. Hardcoded constants require code changes,
code review, and a redeployment to update. A YAML file can be updated by
someone with no Python knowledge, and the diff is trivially auditable
("80C limit changed from 150000 to X").

**Why not extract constants from the embedded tax law text?**
This would require the LLM to read a number from a document and use it
in arithmetic — combining two failure modes (OCR/retrieval errors and
LLM arithmetic) in a single code path. Separating "what the law says"
(embedded text) from "what the numbers are" (YAML config) means each
can be updated and validated independently.

**Trade-off accepted:**
Adding a new assessment year requires two manual steps: updating
`tax_constants.yaml` and ingesting new knowledge base documents. This
is intentional friction — a human should verify both before the new
year goes live.

---

## 4. LangSmith redaction middleware

**Decision:** Strip financial values from LangSmith trace payloads before
they leave the process, rather than disabling tracing or using LangSmith's
built-in masking.

**Why not disable tracing entirely?**
Latency, token counts, and retrieval hit rates are genuinely useful for
debugging and improving the system. Disabling tracing throws away that
signal.

**Why not use LangSmith's built-in masking?**
LangSmith's masking operates on the LangSmith server side — the data
still travels over the network before being masked. For financial data,
the boundary that matters is the process boundary. Data that never leaves
the process is categorically more private than data that travels encrypted
and is masked at the destination.

**What gets logged:**
Structural metadata only — which fields were extracted, confidence scores,
latency, token counts, assessment year, deduction category. No monetary
values, no PAN, no names.

**Trade-off accepted:**
Redacted traces are less useful for debugging extraction errors since
you can't see the actual values that caused a failure. In practice,
extraction is deterministic enough (100% eval accuracy) that this is
not a significant operational concern.

---

## 5. Two separate Railway services over a single container

**Decision:** Deploy FastAPI and Streamlit as two separate Railway services
rather than combining them into a single container with a process manager.

**Why separate services?**
Independent deployability — a frontend change (Streamlit) doesn't require
restarting the backend (FastAPI) and clearing all active user sessions.
Independent scaling — the stateless Streamlit service can be scaled
horizontally without affecting the stateful session manager in FastAPI.
Cleaner failure isolation — a Streamlit crash doesn't take down the API.

**Trade-off accepted:**
Streamlit makes HTTP calls to FastAPI over the public internet (Railway's
external network) rather than localhost. This adds ~5-20ms latency per
request and technically exposes the API publicly. The API has no
authentication layer beyond session ID validation, which is acceptable
for a portfolio demo but would need an API key or JWT layer in production.

---

## 6. Keyword-based RAG scorer over RAGAs

**Decision:** Implement a lightweight keyword-overlap faithfulness and
relevance scorer rather than using the RAGAs library with an LLM judge.

**Why not RAGAs?**
RAGAs requires either OpenAI or a self-hosted LLM as a judge model,
adding a second LLM dependency to the eval pipeline and significant
per-run cost. For CI runs on every push, LLM-judge-based eval would
cost money proportional to commit frequency — a poor trade-off for a
portfolio project.

**Why keyword overlap is sufficient here?**
The ground truth answers in `ground_truth.json` are precise and
numerical. A faithful answer to "what is your 80D deduction?" must
contain the number "67,000" — keyword overlap catches this directly.
An LLM judge adds probabilistic noise to what is fundamentally a
deterministic correctness check.

**Trade-off accepted:**
Keyword overlap penalizes paraphrasing — Claude saying "₹67k" instead
of "₹67,000" lowers the score even though both are correct. This is
why faithfulness scores at 80.6% rather than higher. The actual answer
quality observed in manual review is higher than the automated score
suggests.