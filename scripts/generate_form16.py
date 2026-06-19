import yaml
import os
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ── config ────────────────────────────────────────────────────────────────────

PERSONAS_PATH = Path("synthetic_data/personas.yaml")
OUTPUT_DIR    = Path("synthetic_data/form16")

# ── helpers ───────────────────────────────────────────────────────────────────

def load_personas():
    with open(PERSONAS_PATH, "r") as f:
        return yaml.safe_load(f)["personas"]

def currency(amount: int) -> str:
    return f"Rs. {amount:,.0f}"

def compute_form16_values(p: dict) -> dict:
    s = p["salary"]
    inv = p["investments"]
    hi  = p["health_insurance"]

    gross           = s["gross_annual"]
    basic           = s["basic_annual"]
    hra_received    = s["hra_annual"]
    special         = s["special_allowance_annual"]
    tds             = s["tds_deducted"]
    rent_monthly    = p["rent_paid_monthly"]

    # Standard deduction (AY 2026-27 new regime = 75k, old regime = 50k)
    std_deduction = 75000

    # HRA exemption (Rule 2A) — only if rent is paid
    hra_exemption = 0
    if rent_monthly > 0:
        rent_annual    = rent_monthly * 12
        salary_for_hra = basic  # HRA computed on basic
        if p["metro"]:
            hra_exemption = min(
                hra_received,
                0.50 * salary_for_hra,
                rent_annual - 0.10 * salary_for_hra
            )
        else:
            hra_exemption = min(
                hra_received,
                0.40 * salary_for_hra,
                rent_annual - 0.10 * salary_for_hra
            )
        hra_exemption = max(0, int(hra_exemption))

    taxable_hra    = hra_received - hra_exemption
    gross_taxable  = gross - hra_exemption

    # Deductions under Chapter VI-A
    deduction_80C = min(inv["section_80C"], 150000)

    # 80D
    self_80d    = min(hi["self_premium"], 25000)
    parent_limit = 50000 if hi["parents_senior_citizen"] else 25000
    parent_80d  = min(hi["parents_premium"], parent_limit)
    deduction_80D = self_80d + parent_80d

    total_deductions = std_deduction + deduction_80C + deduction_80D
    net_taxable      = max(0, gross_taxable - total_deductions)

    return {
        "gross":            gross,
        "basic":            basic,
        "hra_received":     hra_received,
        "special":          special,
        "hra_exemption":    hra_exemption,
        "taxable_hra":      taxable_hra,
        "gross_taxable":    gross_taxable,
        "std_deduction":    std_deduction,
        "deduction_80C":    deduction_80C,
        "deduction_80D":    deduction_80D,
        "total_deductions": total_deductions,
        "net_taxable":      net_taxable,
        "tds":              tds,
    }

# ── PDF builder ───────────────────────────────────────────────────────────────

def build_form16(p: dict, v: dict, output_path: Path):
    doc    = SimpleDocTemplate(str(output_path), pagesize=A4,
                               topMargin=15*mm, bottomMargin=15*mm,
                               leftMargin=20*mm, rightMargin=20*mm)
    styles = getSampleStyleSheet()
    title_style  = ParagraphStyle("title",  fontSize=11, alignment=TA_CENTER, fontName="Helvetica-Bold")
    header_style = ParagraphStyle("header", fontSize=9,  alignment=TA_CENTER, fontName="Helvetica-Bold")
    normal_style = ParagraphStyle("normal", fontSize=8,  alignment=TA_LEFT,   fontName="Helvetica")

    story = []

    # ── PART A ────────────────────────────────────────────────────────────────
    story.append(Paragraph("FORM 16", title_style))
    story.append(Paragraph("[See rule 31(1)(a)]", header_style))
    story.append(Paragraph(
        "Certificate under section 203 of the Income-tax Act, 1961 for tax deducted at source on salary",
        header_style
    ))
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("PART A", title_style))
    story.append(Spacer(1, 3*mm))

    part_a_data = [
        ["Assessment Year", f"{p['assessment_year']}", "Period", f"01-Apr-{p['financial_year'][:4]} to 31-Mar-{p['financial_year'][-2:]}"],
        ["Name of Employer", p["employer"], "TAN of Employer", p["employer_tan"]],
        ["Name of Employee", p["name"], "PAN of Employee", p["pan"]],
        ["Designation", "Salaried Employee", "City", p["city"]],
    ]

    part_a_table = Table(part_a_data, colWidths=[45*mm, 65*mm, 35*mm, 45*mm])
    part_a_table.setStyle(TableStyle([
        ("FONTNAME",    (0,0), (-1,-1), "Helvetica"),
        ("FONTNAME",    (0,0), (0,-1),  "Helvetica-Bold"),
        ("FONTNAME",    (2,0), (2,-1),  "Helvetica-Bold"),
        ("FONTSIZE",    (0,0), (-1,-1), 8),
        ("GRID",        (0,0), (-1,-1), 0.5, colors.black),
        ("BACKGROUND",  (0,0), (0,-1),  colors.lightgrey),
        ("BACKGROUND",  (2,0), (2,-1),  colors.lightgrey),
        ("PADDING",     (0,0), (-1,-1), 4),
    ]))
    story.append(part_a_table)
    story.append(Spacer(1, 4*mm))

    # TDS summary table
    story.append(Paragraph("Summary of Tax Deducted at Source", header_style))
    story.append(Spacer(1, 2*mm))

    tds_per_quarter = v["tds"] // 4
    tds_remainder   = v["tds"] - tds_per_quarter * 3

    tds_data = [
        ["Quarter", "Date of Payment", "Amount Paid (Rs.)", "TDS Deducted (Rs.)", "TDS Deposited (Rs.)"],
        ["Q1 (Apr–Jun)", "15-Jul-2025", currency(v["gross"]//4), currency(tds_per_quarter), currency(tds_per_quarter)],
        ["Q2 (Jul–Sep)", "15-Oct-2025", currency(v["gross"]//4), currency(tds_per_quarter), currency(tds_per_quarter)],
        ["Q3 (Oct–Dec)", "15-Jan-2026", currency(v["gross"]//4), currency(tds_per_quarter), currency(tds_per_quarter)],
        ["Q4 (Jan–Mar)", "15-Apr-2026", currency(v["gross"]//4), currency(tds_remainder),   currency(tds_remainder)],
        ["Total",        "",            currency(v["gross"]),     currency(v["tds"]),         currency(v["tds"])],
    ]

    tds_table = Table(tds_data, colWidths=[30*mm, 35*mm, 40*mm, 40*mm, 40*mm])
    tds_table.setStyle(TableStyle([
        ("FONTNAME",    (0,0), (-1,-1),  "Helvetica"),
        ("FONTNAME",    (0,0), (-1,0),   "Helvetica-Bold"),
        ("FONTNAME",    (0,-1),(0,-1),   "Helvetica-Bold"),
        ("FONTSIZE",    (0,0), (-1,-1),  7.5),
        ("GRID",        (0,0), (-1,-1),  0.5, colors.black),
        ("BACKGROUND",  (0,0), (-1,0),   colors.lightgrey),
        ("BACKGROUND",  (0,-1),(-1,-1),  colors.lightgrey),
        ("ALIGN",       (2,0), (-1,-1),  "RIGHT"),
        ("PADDING",     (0,0), (-1,-1),  4),
    ]))
    story.append(tds_table)
    story.append(Spacer(1, 8*mm))

    # ── PART B ────────────────────────────────────────────────────────────────
    story.append(Paragraph("PART B", title_style))
    story.append(Paragraph("Details of Salary Paid and any other income and tax deducted", header_style))
    story.append(Spacer(1, 3*mm))

    part_b_data = [
        ["PARTICULARS", "AMOUNT (Rs.)", "AMOUNT (Rs.)"],

        ["1. GROSS SALARY", "", ""],
        ["   (a) Salary as per provisions of sec 17(1)", currency(v["basic"] + v["special"]), ""],
        ["   (b) House Rent Allowance u/s 17(1)", currency(v["hra_received"]), ""],
        ["   (c) Total Gross Salary", "", currency(v["gross"])],

        ["2. LESS: EXEMPTIONS u/s 10", "", ""],
        ["   (a) HRA Exemption u/s 10(13A)", currency(v["hra_exemption"]), ""],
        ["   Total Exemptions", "", currency(v["hra_exemption"])],

        ["3. BALANCE (Gross Taxable Salary)", "", currency(v["gross_taxable"])],

        ["4. DEDUCTIONS UNDER CHAPTER VI-A", "", ""],
        ["   (a) Standard Deduction u/s 16(ia)", currency(v["std_deduction"]), ""],
        ["   (b) Section 80C", currency(v["deduction_80C"]), ""],
        ["   (c) Section 80D", currency(v["deduction_80D"]), ""],
        ["   Total Deductions", "", currency(v["total_deductions"])],

        ["5. NET TAXABLE INCOME", "", currency(v["net_taxable"])],
        ["6. TAX DEDUCTED AT SOURCE (TDS)", "", currency(v["tds"])],
    ]

    part_b_table = Table(part_b_data, colWidths=[100*mm, 40*mm, 50*mm])
    part_b_table.setStyle(TableStyle([
        ("FONTNAME",    (0,0),  (-1,-1),  "Helvetica"),
        ("FONTNAME",    (0,0),  (-1,0),   "Helvetica-Bold"),
        ("FONTNAME",    (0,1),  (0,1),    "Helvetica-Bold"),
        ("FONTNAME",    (0,5),  (0,5),    "Helvetica-Bold"),
        ("FONTNAME",    (0,9),  (0,9),    "Helvetica-Bold"),
        ("FONTNAME",    (0,13), (0,13),   "Helvetica-Bold"),
        ("FONTNAME",    (0,14), (-1,14),  "Helvetica-Bold"),
        ("FONTNAME",    (0,15), (-1,15),  "Helvetica-Bold"),
        ("FONTSIZE",    (0,0),  (-1,-1),  8),
        ("GRID",        (0,0),  (-1,-1),  0.5, colors.black),
        ("BACKGROUND",  (0,0),  (-1,0),   colors.lightgrey),
        ("BACKGROUND",  (0,14),(-1,14),   colors.lightyellow),
        ("BACKGROUND",  (0,15),(-1,15),   colors.lightyellow),
        ("ALIGN",       (1,0),  (-1,-1),  "RIGHT"),
        ("PADDING",     (0,0),  (-1,-1),  4),
        ("SPAN",        (0,0),  (0,0)),
    ]))
    story.append(part_b_table)
    story.append(Spacer(1, 8*mm))

    # Signature block
    sig_data = [
        ["", "For " + p["employer"]],
        ["Place: " + p["city"], ""],
        ["Date: 31-May-2026", "Authorised Signatory"],
    ]
    sig_table = Table(sig_data, colWidths=[90*mm, 100*mm])
    sig_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("ALIGN",    (1,0), (1,-1),  "RIGHT"),
    ]))
    story.append(sig_table)

    doc.build(story)
    print(f"  ✓ {output_path.name}")

# ── entry point ───────────────────────────────────────────────────────────────

def main():
    personas = load_personas()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating Form 16 PDFs for {len(personas)} personas...\n")
    for p in personas:
        v = compute_form16_values(p)
        output_path = OUTPUT_DIR / f"form16_{p['id']}_{p['name'].replace(' ', '_')}.pdf"
        build_form16(p, v, output_path)

    print(f"\n✓ Done. PDFs saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    main()