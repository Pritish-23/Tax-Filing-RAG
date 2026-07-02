import sys
import json
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from dotenv import load_dotenv
load_dotenv()

from extract_documents import extract_all
from session_manager import store
from deduction_engine import run_tax_analysis
from rag_engine import answer_question
from tax_calculator import compare_regimes

# ── config ────────────────────────────────────────────────────────────────────

GROUND_TRUTH_PATH = Path("evaluation/ground_truth.json")
RESULTS_DIR       = Path("evaluation/results")
FORM16_DIR        = Path("synthetic_data/form16")
BANK_DIR          = Path("synthetic_data/bank_statements")
PERSONAS_PATH     = Path("synthetic_data/personas.yaml")

# ── result dataclasses ────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    persona_id:    str
    passed:        int
    total:         int
    accuracy:      float

@dataclass
class RegimeResult:
    persona_id:    str
    expected:      str
    got:           str
    matched:       bool
    old_tax:       int
    new_tax:       int
    savings:       int

@dataclass
class RAGResult:
    persona_id:    str
    question:      str
    expected:      str
    actual:        str
    faithfulness:  float   # does answer match retrieved context
    relevance:     float   # does answer address the question

@dataclass
class EvalSummary:
    run_timestamp:        str
    extraction_accuracy:  float
    regime_accuracy:      float
    avg_faithfulness:     float
    avg_relevance:        float
    overall_score:        float
    total_personas:       int
    total_rag_pairs:      int

# ── helpers ───────────────────────────────────────────────────────────────────

def load_ground_truth():
    with open(GROUND_TRUTH_PATH, "r") as f:
        return json.load(f)

def load_personas():
    import yaml
    with open(PERSONAS_PATH, "r") as f:
        return {p["id"]: p for p in yaml.safe_load(f)["personas"]}

def get_persona_files(pid: str, name: str):
    name_clean = name.replace(" ", "_")
    return (
        FORM16_DIR / f"form16_{pid}_{name_clean}.pdf",
        BANK_DIR   / f"bank_statement_{pid}_{name_clean}.csv",
    )

# ── simple faithfulness scorer ────────────────────────────────────────────────
# RAGAs requires OpenAI by default so we use a lightweight keyword-based scorer
# that measures whether key expected facts appear in the actual answer.
# This is sufficient for portfolio demonstration purposes.

def score_faithfulness(expected: str, actual: str) -> float:
    """
    Checks what fraction of key numeric/factual tokens from the expected
    answer appear in the actual answer.
    """
    import re
    # extract numbers and key terms from expected
    numbers  = set(re.findall(r"[\d,]+", expected))
    keywords = set(w.lower() for w in re.findall(r"\b[A-Z][a-z]+\b", expected))
    tokens   = numbers | keywords
    if not tokens:
        return 1.0
    actual_lower = actual.lower()
    matched = sum(1 for t in tokens if t.replace(",", "") in actual_lower.replace(",", ""))
    return round(matched / len(tokens), 2)

def score_relevance(question: str, actual: str) -> float:
    """
    Checks whether key question terms appear in the actual answer.
    """
    import re
    q_terms  = set(w.lower() for w in re.findall(r"\b\w{4,}\b", question))
    if not q_terms:
        return 1.0
    actual_lower = actual.lower()
    matched = sum(1 for t in q_terms if t in actual_lower)
    return round(matched / len(q_terms), 2)

# ── dimension 1: extraction accuracy ─────────────────────────────────────────

def eval_extraction(personas: dict) -> list[ExtractionResult]:
    from generate_form16 import compute_form16_values
    
    print("\n[1/3] Evaluating extraction accuracy...")
    results = []

    for pid, p in personas.items():
        form16_path, bank_path = get_persona_files(pid, p["name"])
        if not form16_path.exists():
            continue

        extracted = extract_all(form16_path, bank_path, session_id=f"eval-{pid}")
        expected  = compute_form16_values(p)
        inv       = p["investments"]
        hi        = p["health_insurance"]

        checks = [
            abs(expected["gross"]         - extracted.form16.gross_salary)           <= 1,
            abs(expected["tds"]           - extracted.form16.tds_deducted)            <= 1,
            abs(expected["hra_exemption"] - extracted.form16.hra_exemption_claimed)  <= 1,
            abs(expected["std_deduction"] - extracted.form16.standard_deduction)     <= 1,
            abs(expected["deduction_80C"] - extracted.form16.deduction_80C_claimed)  <= 1,
            abs(expected["deduction_80D"] - extracted.form16.deduction_80D_claimed)  <= 1,
            abs(expected["net_taxable"]   - extracted.form16.net_taxable_income)     <= 1,
            abs(inv["lic_premium"]         - extracted.investments.total_lic_premium)           <= 1,
            abs(inv["ppf"]                 - extracted.investments.total_ppf_deposit)            <= 1,
            abs(inv["elss"]                - extracted.investments.total_elss_investment)        <= 1,
            abs(hi["self_premium"]         - extracted.investments.total_self_health_premium)    <= 1,
            abs(hi["parents_premium"]      - extracted.investments.total_parents_health_premium) <= 1,
            abs(p["rent_paid_monthly"]*12  - extracted.investments.total_rent_paid_annual)       <= 1,
        ]

        passed = sum(checks)
        total  = len(checks)
        results.append(ExtractionResult(
            persona_id=pid,
            passed=passed,
            total=total,
            accuracy=round(passed/total, 2),
        ))
        print(f"  {pid}: {passed}/{total}")

    return results

# ── dimension 2: regime recommendation accuracy ───────────────────────────────

def eval_regime(personas: dict) -> list[RegimeResult]:
    print("\n[2/3] Evaluating regime recommendations...")
    results = []

    for pid, p in personas.items():
        s   = p["salary"]
        inv = p["investments"]
        hi  = p["health_insurance"]

        comparison = compare_regimes(
            gross_salary=s["gross_annual"],
            basic_salary=s["basic_annual"],
            hra_received=s["hra_annual"],
            rent_paid_annual=p["rent_paid_monthly"] * 12,
            is_metro=p["metro"],
            raw_80C=inv["section_80C"],
            self_health_premium=hi["self_premium"],
            parents_health_premium=hi["parents_premium"],
            parents_senior_citizen=hi["parents_senior_citizen"],
            ay=p["assessment_year"],
        )

        matched = comparison.recommended == p["expected_regime"]
        results.append(RegimeResult(
            persona_id=pid,
            expected=p["expected_regime"],
            got=comparison.recommended,
            matched=matched,
            old_tax=comparison.old_regime.total_tax,
            new_tax=comparison.new_regime.total_tax,
            savings=comparison.savings,
        ))
        symbol = "✓" if matched else "✗"
        print(f"  {pid}: {symbol} expected={p['expected_regime']} got={comparison.recommended} savings=Rs.{comparison.savings:,}")

    return results

# ── dimension 3: RAG quality ──────────────────────────────────────────────────

def eval_rag(ground_truth: dict, personas: dict) -> list[RAGResult]:
    print("\n[3/3] Evaluating RAG answer quality...")
    results   = []
    seen_pids = {}  # cache sessions per persona

    for pair in ground_truth["evaluation_pairs"]:
        pid  = pair["persona_id"]
        p    = personas[pid]

        # Reuse session if already created for this persona
        if pid not in seen_pids:
            form16_path, bank_path = get_persona_files(pid, p["name"])
            financials  = extract_all(form16_path, bank_path, session_id=f"eval-rag-{pid}")
            session_id  = store.create_session(financials)
            analysis    = run_tax_analysis(
                financials,
                is_metro=p["metro"],
                parents_senior_citizen=p["health_insurance"]["parents_senior_citizen"],
            )
            seen_pids[pid] = (session_id, analysis)

        session_id, analysis = seen_pids[pid]
        collection = store.get_collection(session_id)

        print(f"  {pid} — {pair['question'][:60]}...")
        actual = answer_question(
            query=pair["question"],
            analysis=analysis,
            session_collection=collection,
            deduction_category=pair.get("deduction_category"),
        )
        time.sleep(0.5)  # avoid rate limiting

        faithfulness = score_faithfulness(pair["expected_answer"], actual)
        relevance    = score_relevance(pair["question"], actual)

        results.append(RAGResult(
            persona_id=pid,
            question=pair["question"],
            expected=pair["expected_answer"],
            actual=actual,
            faithfulness=faithfulness,
            relevance=relevance,
        ))
        print(f"    faithfulness={faithfulness} relevance={relevance}")

    # Clean up sessions
    for session_id, _ in seen_pids.values():
        store.delete_session(session_id)

    return results

# ── summary + save ─────────────────────────────────────────────────────────────

def save_results(extraction, regime, rag, summary):
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output = {
        "summary":    asdict(summary),
        "extraction": [asdict(r) for r in extraction],
        "regime":     [asdict(r) for r in regime],
        "rag":        [asdict(r) for r in rag],
    }

    path = RESULTS_DIR / f"eval_{timestamp}.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved → {path}")
    return path

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Tax Filing RAG — Evaluation Harness")
    print("=" * 60)

    ground_truth = load_ground_truth()
    personas     = load_personas()

    extraction_results = eval_extraction(personas)
    regime_results     = eval_regime(personas)
    rag_results        = eval_rag(ground_truth, personas)

    # ── compute summary scores ────────────────────────────────────────────────
    extraction_accuracy = round(
        sum(r.passed for r in extraction_results) /
        sum(r.total  for r in extraction_results), 3
    )
    regime_accuracy = round(
        sum(1 for r in regime_results if r.matched) / len(regime_results), 3
    )
    avg_faithfulness = round(
        sum(r.faithfulness for r in rag_results) / len(rag_results), 3
    )
    avg_relevance = round(
        sum(r.relevance for r in rag_results) / len(rag_results), 3
    )
    overall_score = round(
        (extraction_accuracy + regime_accuracy + avg_faithfulness + avg_relevance) / 4, 3
    )

    summary = EvalSummary(
        run_timestamp=datetime.now().isoformat(),
        extraction_accuracy=extraction_accuracy,
        regime_accuracy=regime_accuracy,
        avg_faithfulness=avg_faithfulness,
        avg_relevance=avg_relevance,
        overall_score=overall_score,
        total_personas=len(personas),
        total_rag_pairs=len(rag_results),
    )

    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Extraction accuracy:   {extraction_accuracy*100:.1f}%")
    print(f"Regime accuracy:       {regime_accuracy*100:.1f}%")
    print(f"Avg faithfulness:      {avg_faithfulness*100:.1f}%")
    print(f"Avg relevance:         {avg_relevance*100:.1f}%")
    print(f"Overall score:         {overall_score*100:.1f}%")
    print("=" * 60)

    save_results(extraction_results, regime_results, rag_results, summary)

if __name__ == "__main__":
    main()