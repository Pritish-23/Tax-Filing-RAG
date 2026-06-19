import yaml
import csv
import random
from pathlib import Path
from datetime import date, timedelta

# ── config ────────────────────────────────────────────────────────────────────

PERSONAS_PATH = Path("synthetic_data/personas.yaml")
OUTPUT_DIR    = Path("synthetic_data/bank_statements")
RANDOM_SEED   = 42  # fixed seed so statements are reproducible

# ── helpers ───────────────────────────────────────────────────────────────────

def load_personas():
    with open(PERSONAS_PATH, "r") as f:
        return yaml.safe_load(f)["personas"]

def random_date_in_month(year: int, month: int, rng: random.Random) -> date:
    if month == 12:
        end_day = 31
    else:
        end_day = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, rng.randint(1, end_day))

def salary_credit_date(month: int) -> date:
    """Salary credited on last working day — simplified as 28th."""
    year = 2025 if month >= 4 else 2026
    return date(year, month, 28)

def format_date(d: date) -> str:
    return d.strftime("%d-%b-%Y")

# ── transaction generators ────────────────────────────────────────────────────

def generate_salary_credits(p: dict, rng: random.Random) -> list[dict]:
    monthly_salary = p["salary"]["gross_annual"] // 12
    transactions   = []
    months = list(range(4, 13)) + list(range(1, 4))  # Apr 2025 → Mar 2026

    for month in months:
        year = 2025 if month >= 4 else 2026
        transactions.append({
            "date":        format_date(salary_credit_date(month)),
            "description": f"SALARY CREDIT - {p['employer'].upper()} - {date(year, month, 1).strftime('%b %Y').upper()}",
            "debit":       "",
            "credit":      monthly_salary,
            "balance":     None,  # computed later
            "category":    "SALARY",
            "tag":         ""
        })
    return transactions

def generate_rent_debits(p: dict, rng: random.Random) -> list[dict]:
    if p["rent_paid_monthly"] == 0:
        return []
    transactions = []
    months = list(range(4, 13)) + list(range(1, 4))
    for month in months:
        year = 2025 if month >= 4 else 2026
        transactions.append({
            "date":        format_date(date(year, month, rng.randint(1, 5))),
            "description": f"NEFT - RENT PAYMENT - {date(year, month, 1).strftime('%b %Y').upper()}",
            "debit":       p["rent_paid_monthly"],
            "credit":      "",
            "balance":     None,
            "category":    "RENT",
            "tag":         "HRA_RENT"
        })
    return transactions

def generate_investment_transactions(p: dict, rng: random.Random) -> list[dict]:
    transactions = []
    inv = p["investments"]
    hi  = p["health_insurance"]

    # ── LIC Premium (annual, typically April or March) ──────────────────────
    if inv.get("lic_premium", 0) > 0:
        transactions.append({
            "date":        format_date(date(2025, rng.choice([4, 5]), rng.randint(5, 20))),
            "description": "LIC PREMIUM PAYMENT - POLICY AUTO DEBIT",
            "debit":       inv["lic_premium"],
            "credit":      "",
            "balance":     None,
            "category":    "INVESTMENT",
            "tag":         "80C_LIC"
        })

    # ── PPF Deposit (one or two tranches) ────────────────────────────────────
    if inv.get("ppf", 0) > 0:
        ppf_amount = inv["ppf"]
        split      = rng.choice([True, False])
        if split and ppf_amount >= 10000:
            half = ppf_amount // 2
            for m in rng.sample([4, 7, 10, 1], 2):
                year = 2025 if m >= 4 else 2026
                transactions.append({
                    "date":        format_date(date(year, m, rng.randint(5, 25))),
                    "description": "PPF DEPOSIT - SBI PPF ACCOUNT",
                    "debit":       half,
                    "credit":      "",
                    "balance":     None,
                    "category":    "INVESTMENT",
                    "tag":         "80C_PPF"
                })
        else:
            transactions.append({
                "date":        format_date(date(2025, rng.choice([4, 5, 6]), rng.randint(5, 25))),
                "description": "PPF DEPOSIT - SBI PPF ACCOUNT",
                "debit":       ppf_amount,
                "credit":      "",
                "balance":     None,
                "category":    "INVESTMENT",
                "tag":         "80C_PPF"
            })

    # ── ELSS SIP (monthly) ───────────────────────────────────────────────────
    if inv.get("elss", 0) > 0:
        monthly_sip = inv["elss"] // 12
        months      = list(range(4, 13)) + list(range(1, 4))
        for month in months:
            year = 2025 if month >= 4 else 2026
            transactions.append({
                "date":        format_date(date(year, month, rng.randint(1, 10))),
                "description": f"SIP DEBIT - AXIS ELSS FUND - {date(year, month, 1).strftime('%b-%Y').upper()}",
                "debit":       monthly_sip,
                "credit":      "",
                "balance":     None,
                "category":    "INVESTMENT",
                "tag":         "80C_ELSS"
            })

    # ── Health Insurance Premium (self) ──────────────────────────────────────
    if hi.get("self_premium", 0) > 0:
        transactions.append({
            "date":        format_date(date(2025, rng.choice([4, 5]), rng.randint(1, 15))),
            "description": "HEALTH INSURANCE PREMIUM - STAR HEALTH - SELF/FAMILY",
            "debit":       hi["self_premium"],
            "credit":      "",
            "balance":     None,
            "category":    "INSURANCE",
            "tag":         "80D_SELF"
        })

    # ── Health Insurance Premium (parents) ───────────────────────────────────
    if hi.get("parents_premium", 0) > 0:
        transactions.append({
            "date":        format_date(date(2025, rng.choice([4, 5, 6]), rng.randint(1, 15))),
            "description": "HEALTH INSURANCE PREMIUM - STAR HEALTH - PARENTS",
            "debit":       hi["parents_premium"],
            "credit":      "",
            "balance":     None,
            "category":    "INSURANCE",
            "tag":         "80D_PARENTS"
        })

    return transactions

def generate_living_expenses(p: dict, rng: random.Random) -> list[dict]:
    """Generate realistic monthly living expenses to make the statement look real."""
    transactions = []
    monthly_salary = p["salary"]["gross_annual"] // 12

    expense_templates = [
        ("GROCERY - BIGBASKET / DMART",        0.03, 0.05, "EXPENSE"),
        ("UPI - ZOMATO / SWIGGY FOOD ORDER",   0.01, 0.02, "EXPENSE"),
        ("ELECTRICITY BILL PAYMENT - MSEB",    0.01, 0.02, "EXPENSE"),
        ("MOBILE RECHARGE - AIRTEL",           0.003, 0.005, "EXPENSE"),
        ("OTT SUBSCRIPTION - NETFLIX/PRIME",   0.001, 0.002, "EXPENSE"),
        ("FUEL - HPCL PETROL PUMP",            0.01, 0.02, "EXPENSE"),
        ("ATM CASH WITHDRAWAL",                0.02, 0.04, "EXPENSE"),
        ("AMAZON SHOPPING",                    0.01, 0.03, "EXPENSE"),
    ]

    months = list(range(4, 13)) + list(range(1, 4))
    for month in months:
        year = 2025 if month >= 4 else 2026
        # pick 3-5 random expenses per month
        selected = rng.sample(expense_templates, rng.randint(3, 5))
        for desc, min_pct, max_pct, cat in selected:
            amount = int(monthly_salary * rng.uniform(min_pct, max_pct))
            amount = max(amount, 200)  # floor
            transactions.append({
                "date":        format_date(random_date_in_month(year, month, rng)),
                "description": desc,
                "debit":       amount,
                "credit":      "",
                "balance":     None,
                "category":    cat,
                "tag":         ""
            })

    return transactions

# ── balance computation ───────────────────────────────────────────────────────

def compute_balances(transactions: list[dict], opening_balance: int) -> list[dict]:
    sorted_txns = sorted(transactions, key=lambda x: x["date"])
    balance = opening_balance
    for txn in sorted_txns:
        credit = txn["credit"] if txn["credit"] != "" else 0
        debit  = txn["debit"]  if txn["debit"]  != "" else 0
        balance = balance + credit - debit
        txn["balance"] = balance
    return sorted_txns

# ── CSV writer ────────────────────────────────────────────────────────────────

def write_csv(transactions: list[dict], output_path: Path, p: dict):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Bank header block
        writer.writerow(["ACCOUNT STATEMENT"])
        writer.writerow(["Bank Name:", "State Bank of India"])
        writer.writerow(["Account Holder:", p["name"]])
        writer.writerow(["PAN:", p["pan"]])
        writer.writerow(["Account Number:", f"XXXXX{p['id'][1:]}6789"])
        writer.writerow(["IFSC Code:", f"SBIN000{p['id'][1:]}45"])
        writer.writerow(["Branch:", p["city"]])
        writer.writerow(["Statement Period:", "01-Apr-2025 to 31-Mar-2026"])
        writer.writerow([])

        # Transactions header
        writer.writerow(["Date", "Description", "Debit (Rs.)", "Credit (Rs.)", "Balance (Rs.)", "Category", "Tag"])

        for txn in transactions:
            writer.writerow([
                txn["date"],
                txn["description"],
                txn["debit"],
                txn["credit"],
                txn["balance"],
                txn["category"],
                txn["tag"],
            ])

    print(f"  ✓ {output_path.name} ({len(transactions)} transactions)")

# ── entry point ───────────────────────────────────────────────────────────────

def main():
    personas = load_personas()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(RANDOM_SEED)

    print(f"Generating bank statements for {len(personas)} personas...\n")

    for p in personas:
        opening_balance = rng.randint(50000, 150000)

        transactions = (
            generate_salary_credits(p, rng) +
            generate_rent_debits(p, rng) +
            generate_investment_transactions(p, rng) +
            generate_living_expenses(p, rng)
        )

        transactions = compute_balances(transactions, opening_balance)

        output_path = OUTPUT_DIR / f"bank_statement_{p['id']}_{p['name'].replace(' ', '_')}.csv"
        write_csv(transactions, output_path, p)

    print(f"\n✓ Done. Bank statements saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    main()