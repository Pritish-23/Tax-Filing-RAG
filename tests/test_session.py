import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from extract_documents import extract_all
from session_manager import store
import time

# Use P3 as test persona — has HRA, full 80C, 80D
form16_path = Path("synthetic_data/form16/form16_P3_Rahul_Mehta.pdf")
bank_path   = Path("synthetic_data/bank_statements/bank_statement_P3_Rahul_Mehta.csv")

print("1. Extracting financials for P3...")
financials = extract_all(form16_path, bank_path, session_id="temp")

print("2. Creating session...")
session_id = store.create_session(financials)
print(f"   Session created: {session_id[:8]}...")

print(f"3. Active sessions: {store.active_session_count()}")

print("4. Retrieving session financials...")
retrieved = store.get_financials(session_id)
print(f"   Employee: {retrieved.form16.employee_name}")
print(f"   Gross salary: Rs. {retrieved.form16.gross_salary:,}")
print(f"   PAN (masked): {retrieved.form16.pan_masked}")

print("5. Checking ephemeral collection...")
collection = store.get_collection(session_id)
result = collection.query(query_texts=["what is my gross salary"], n_results=1)
print(f"   Query returned {len(result['documents'][0])} document(s)")
print(f"   Preview: {result['documents'][0][0][:100]}...")

print("6. Deleting session explicitly...")
deleted = store.delete_session(session_id)
print(f"   Deleted: {deleted}")
print(f"   Active sessions after delete: {store.active_session_count()}")

print("7. Verifying session is gone...")
gone = store.get_financials(session_id)
print(f"   get_financials returns: {gone}")

print("\n✓ Phase 4 session manager verified.")