import sys
import yaml
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from tax_calculator import compare_regimes

PERSONAS_PATH = Path("synthetic_data/personas.yaml")

def load_personas():
    with open(PERSONAS_PATH, "r") as f:
        return yaml.safe_load(f)["personas"]

def main():
    personas = load_personas()
    print(f"{'ID':<5} {'Name':<20} {'Old Tax':>10} {'New Tax':>10} {'Recommended':<12} {'Savings':>10} {'Expected':<12} {'Match'}")
    print("-" * 95)

    all_match = True
    for p in personas:
        s   = p["salary"]
        inv = p["investments"]
        hi  = p["health_insurance"]

        result = compare_regimes(
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

        expected  = p["expected_regime"]
        got       = result.recommended
        match     = "✓" if got == expected else "✗"
        if got != expected:
            all_match = False

        print(
            f"{p['id']:<5} {p['name']:<20} "
            f"{result.old_regime.total_tax:>10,} "
            f"{result.new_regime.total_tax:>10,} "
            f"{got:<12} {result.savings:>10,} "
            f"{expected:<12} {match}"
        )

    print("-" * 95)
    if all_match:
        print("✓ All regime recommendations match expected values.")
    else:
        print("✗ Some recommendations differ — review personas or slab constants.")

if __name__ == "__main__":
    main()