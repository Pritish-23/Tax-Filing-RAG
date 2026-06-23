import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from extract_documents import extract_all
from session_manager import store
from deduction_engine import run_tax_analysis
from rag_engine import answer_question, explain_regime_comparison

# Use P5 — has HRA, full 80C, senior citizen parents
form16_path = Path("synthetic_data/form16/form16_P5_Vikram_Reddy.pdf")
bank_path   = Path("synthetic_data/bank_statements/bank_statement_P5_Vikram_Reddy.csv")

print("1. Extracting financials...")
financials = extract_all(form16_path, bank_path, session_id="test-p5")

print("2. Creating session...")
session_id  = store.create_session(financials)
collection  = store.get_collection(session_id)

print("3. Running tax analysis...")
analysis = run_tax_analysis(
    financials,
    is_metro=True,
    parents_senior_citizen=True,
)

print("\n4. Regime comparison explanation:")
print("-" * 60)
explanation = explain_regime_comparison(analysis, collection)
print(explanation)

print("\n5. Deduction question — 80C:")
print("-" * 60)
answer = answer_question(
    query="Can I claim 80C deduction for my LIC premium and ELSS investment?",
    analysis=analysis,
    session_collection=collection,
    deduction_category="80C",
)
print(answer)

print("\n6. Deduction question — 80D parents:")
print("-" * 60)
answer = answer_question(
    query="What is my 80D deduction limit since my parents are senior citizens?",
    analysis=analysis,
    session_collection=collection,
    deduction_category="80D",
)
print(answer)

print("\n7. Cleaning up session...")
store.delete_session(session_id)
print(f"   Session deleted. Active sessions: {store.active_session_count()}")
print("\n✓ Phase 5 RAG engine verified.")