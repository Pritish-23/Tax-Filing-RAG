import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.extraction.extract_documents import extract_all
from pipeline.generate_form16 import compute_form16_values

# ── config ────────────────────────────────────────────────────────────────────

PERSONAS_PATH = Path("synthetic_data/personas.yaml")
FORM16_DIR    = Path("synthetic_data/form16")
BANK_DIR      = Path("synthetic_data/bank_statements")

TOLERANCE = 1  # allow ±1 rupee for rounding differences

# ── helpers ───────────────────────────────────────────────────────────────────

def load_personas():
    with open(PERSONAS_PATH, "r") as f:
        return yaml.safe_load(f)["personas"]

def check(label: str, expected, actual, tolerance=TOLERANCE) -> bool:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        ok = abs(expected - actual) <= tolerance
    else:
        ok = expected == actual
    symbol = "✓" if ok else "✗"
    if not ok:
        print(f"    {symbol} {label}: expected {expected}, got {actual}")
    return ok

# ── main test loop ─────────────────────────────────────────────────────────────

def main():
    personas = load_personas()
    total_checks  = 0
    passed_checks = 0
    persona_results = []

    for p in personas:
        pid  = p["id"]
        name = p["name"].replace(" ", "_")

        form16_path = FORM16_DIR / f"form16_{pid}_{name}.pdf"
        bank_path   = BANK_DIR / f"bank_statement_{pid}_{name}.csv"

        if not form16_path.exists() or not bank_path.exists():
            print(f"[{pid}] MISSING FILES — skipping")
            continue

        # Run extraction
        extracted = extract_all(form16_path, bank_path, session_id=f"test-{pid}")

        # Compute ground truth using the same formulas used to generate the PDF
        expected = compute_form16_values(p)

        print(f"\n[{pid}] {p['name']}")
        checks = []

        checks.append(check("gross_salary",          expected["gross"],            extracted.form16.gross_salary))
        checks.append(check("tds_deducted",            expected["tds"],              extracted.form16.tds_deducted))
        checks.append(check("hra_exemption_claimed",  expected["hra_exemption"],    extracted.form16.hra_exemption_claimed))
        checks.append(check("standard_deduction",     expected["std_deduction"],    extracted.form16.standard_deduction))
        checks.append(check("deduction_80C_claimed",  expected["deduction_80C"],    extracted.form16.deduction_80C_claimed))
        checks.append(check("deduction_80D_claimed",  expected["deduction_80D"],    extracted.form16.deduction_80D_claimed))
        checks.append(check("net_taxable_income",      expected["net_taxable"],      extracted.form16.net_taxable_income))

        # Investment summary checks (from bank statement)
        inv = p["investments"]
        hi  = p["health_insurance"]
        checks.append(check("lic_premium (bank)",      inv["lic_premium"],            extracted.investments.total_lic_premium))
        checks.append(check("ppf_deposit (bank)",       inv["ppf"],                     extracted.investments.total_ppf_deposit))
        checks.append(check("elss_investment (bank)",  inv["elss"],                    extracted.investments.total_elss_investment))
        checks.append(check("self_health_premium (bank)",    hi["self_premium"],     extracted.investments.total_self_health_premium))
        checks.append(check("parents_health_premium (bank)", hi["parents_premium"],  extracted.investments.total_parents_health_premium))

        expected_rent_annual = p["rent_paid_monthly"] * 12
        checks.append(check("rent_paid_annual (bank)", expected_rent_annual,         extracted.investments.total_rent_paid_annual))

        n_passed = sum(checks)
        n_total  = len(checks)
        total_checks  += n_total
        passed_checks += n_passed

        status = "✓ ALL PASS" if n_passed == n_total else f"✗ {n_total - n_passed} FAILED"
        print(f"  {status} ({n_passed}/{n_total})")
        print(f"  extraction_confidence: {extracted.form16.extraction_confidence}")

        persona_results.append((pid, n_passed, n_total))

    print("\n" + "=" * 60)
    print(f"OVERALL: {passed_checks}/{total_checks} field checks passed ({round(100*passed_checks/total_checks, 1)}%)")
    failing = [r for r in persona_results if r[1] < r[2]]
    if failing:
        print(f"\nPersonas with failures: {[r[0] for r in failing]}")
    else:
        print("\n✓ All personas extracted correctly. Phase 3 extraction is verified.")

if __name__ == "__main__":
    main()