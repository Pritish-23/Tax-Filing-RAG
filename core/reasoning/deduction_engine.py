import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from schemas import ExtractedFinancials
from tax_calculator import (
    load_constants, build_deductions,
    compare_regimes, DeductionSummary, RegimeComparison
)

# ── config ────────────────────────────────────────────────────────────────────

CONSTANTS_PATH = Path("data/tax_constants.yaml")

# ── deduction detail (for LLM explanation) ────────────────────────────────────

@dataclass
class DeductionDetail:
    """
    Full breakdown of each deduction with eligibility, amount claimed,
    cap applied, and whether the user is leaving money on the table.
    This feeds the LLM explanation in Layer 3.
    """
    # 80C
    lic_premium_paid:      int
    ppf_deposit_paid:      int
    elss_investment_paid:  int
    raw_80C_total:         int
    cap_80C:               int
    eligible_80C:          int       # min(raw, cap)
    unused_80C_capacity:   int       # how much more they could invest

    # 80D
    self_premium_paid:     int
    parents_premium_paid:  int
    parents_senior_citizen: bool
    self_80D_limit:        int
    parent_80D_limit:      int
    eligible_80D:          int

    # HRA
    hra_received:          int
    rent_paid_annual:      int
    hra_exemption:         int
    hra_taxable:           int       # hra_received - hra_exemption
    is_metro:              bool

    # Standard deduction
    standard_deduction:    int

    # Summary
    total_old_regime_deductions: int  # std + 80C + 80D + HRA
    assessment_year:             str


@dataclass
class FullTaxAnalysis:
    """
    Complete tax analysis for a user session.
    Combines deduction details with regime comparison.
    This is what Phase 5 Layer 3 (LLM) receives as context.
    """
    deduction_detail:  DeductionDetail
    regime_comparison: RegimeComparison
    session_id:        str


# ── main engine ───────────────────────────────────────────────────────────────

def run_tax_analysis(financials: ExtractedFinancials, is_metro: bool, parents_senior_citizen: bool) -> FullTaxAnalysis:
    """
    Main entry point. Takes ExtractedFinancials from Phase 3/4 and
    produces a complete FullTaxAnalysis ready for LLM explanation.
    """
    f16  = financials.form16
    inv  = financials.investments
    ay   = f16.assessment_year

    constants = load_constants(ay)
    limits    = constants["deduction_limits"]

    # ── 80C detail ────────────────────────────────────────────────────────────
    cap_80C          = limits["section_80C"]["max_limit"]
    eligible_80C     = min(inv.total_80C_raw, cap_80C)
    unused_80C       = max(0, cap_80C - inv.total_80C_raw)

    # ── 80D detail ────────────────────────────────────────────────────────────
    self_limit   = limits["section_80D"]["self_spouse_children"]["limit"]
    parent_limit = (limits["section_80D"]["parents"]["senior_citizen_limit"]
                    if parents_senior_citizen
                    else limits["section_80D"]["parents"]["limit"])

    eligible_self_80D   = min(inv.total_self_health_premium, self_limit)
    eligible_parent_80D = min(inv.total_parents_health_premium, parent_limit)
    eligible_80D        = eligible_self_80D + eligible_parent_80D

    # ── standard deduction ────────────────────────────────────────────────────
    std_deduction = constants["standard_deduction"]["old_regime"]

    # ── build deductions via tax_calculator ───────────────────────────────────
    deductions = build_deductions(
        ay=ay,
        gross_salary=f16.gross_salary,
        basic_salary=f16.basic_salary,
        hra_received=f16.hra_received,
        rent_paid_annual=inv.total_rent_paid_annual,
        is_metro=is_metro,
        raw_80C=inv.total_80C_raw,
        self_health_premium=inv.total_self_health_premium,
        parents_health_premium=inv.total_parents_health_premium,
        parents_senior_citizen=parents_senior_citizen,
        constants=constants,
    )

    hra_taxable = max(0, f16.hra_received - deductions.hra_exemption)
    total_old_regime_deductions = (
        std_deduction +
        eligible_80C  +
        eligible_80D  +
        deductions.hra_exemption
    )

    deduction_detail = DeductionDetail(
        lic_premium_paid=inv.total_lic_premium,
        ppf_deposit_paid=inv.total_ppf_deposit,
        elss_investment_paid=inv.total_elss_investment,
        raw_80C_total=inv.total_80C_raw,
        cap_80C=cap_80C,
        eligible_80C=eligible_80C,
        unused_80C_capacity=unused_80C,
        self_premium_paid=inv.total_self_health_premium,
        parents_premium_paid=inv.total_parents_health_premium,
        parents_senior_citizen=parents_senior_citizen,
        self_80D_limit=self_limit,
        parent_80D_limit=parent_limit,
        eligible_80D=eligible_80D,
        hra_received=f16.hra_received,
        rent_paid_annual=inv.total_rent_paid_annual,
        hra_exemption=deductions.hra_exemption,
        hra_taxable=hra_taxable,
        is_metro=is_metro,
        standard_deduction=std_deduction,
        total_old_regime_deductions=total_old_regime_deductions,
        assessment_year=ay,
    )

    # ── regime comparison ─────────────────────────────────────────────────────
    regime_comparison = compare_regimes(
        gross_salary=f16.gross_salary,
        basic_salary=f16.basic_salary,
        hra_received=f16.hra_received,
        rent_paid_annual=inv.total_rent_paid_annual,
        is_metro=is_metro,
        raw_80C=inv.total_80C_raw,
        self_health_premium=inv.total_self_health_premium,
        parents_health_premium=inv.total_parents_health_premium,
        parents_senior_citizen=parents_senior_citizen,
        ay=ay,
    )

    return FullTaxAnalysis(
        deduction_detail=deduction_detail,
        regime_comparison=regime_comparison,
        session_id=financials.session_id,
    )


# ── context builder for LLM ───────────────────────────────────────────────────

def build_llm_context(analysis: FullTaxAnalysis) -> str:
    """
    Converts FullTaxAnalysis into a structured plain-text context block
    that gets injected into the LLM prompt in Layer 3.
    """
    d  = analysis.deduction_detail
    rc = analysis.regime_comparison
    o  = rc.old_regime
    n  = rc.new_regime

    lines = [
        f"=== TAX ANALYSIS FOR AY {d.assessment_year} ===",
        "",
        "--- DEDUCTION BREAKDOWN (Old Regime) ---",
        f"Standard Deduction (Sec 16ia):   Rs. {d.standard_deduction:>10,}",
        f"Section 80C:",
        f"  LIC Premium:                   Rs. {d.lic_premium_paid:>10,}",
        f"  PPF Deposit:                   Rs. {d.ppf_deposit_paid:>10,}",
        f"  ELSS Investment:               Rs. {d.elss_investment_paid:>10,}",
        f"  Total 80C (raw):               Rs. {d.raw_80C_total:>10,}",
        f"  80C Cap:                       Rs. {d.cap_80C:>10,}",
        f"  80C Eligible:                  Rs. {d.eligible_80C:>10,}",
        f"  Unused 80C capacity:           Rs. {d.unused_80C_capacity:>10,}",
        f"Section 80D:",
        f"  Self/Family Premium:           Rs. {d.self_premium_paid:>10,}  (limit: Rs. {d.self_80D_limit:,})",
        f"  Parents Premium:               Rs. {d.parents_premium_paid:>10,}  (limit: Rs. {d.parent_80D_limit:,}  {'senior citizen' if d.parents_senior_citizen else 'non-senior'})",
        f"  80D Eligible:                  Rs. {d.eligible_80D:>10,}",
        f"HRA:",
        f"  HRA Received:                  Rs. {d.hra_received:>10,}",
        f"  Rent Paid (annual):            Rs. {d.rent_paid_annual:>10,}",
        f"  HRA Exemption (Rule 2A):       Rs. {d.hra_exemption:>10,}",
        f"  HRA Taxable:                   Rs. {d.hra_taxable:>10,}",
        f"  City type:                     {'Metro' if d.is_metro else 'Non-metro'}",
        f"Total Old Regime Deductions:     Rs. {d.total_old_regime_deductions:>10,}",
        "",
        "--- REGIME COMPARISON ---",
        f"Old Regime:",
        f"  Taxable Income:                Rs. {o.taxable_income:>10,}",
        f"  Base Tax:                      Rs. {o.base_tax:>10,}",
        f"  Rebate 87A:                    Rs. {o.rebate_87A:>10,}",
        f"  Surcharge:                     Rs. {o.surcharge:>10,}",
        f"  Cess (4%):                     Rs. {o.cess:>10,}",
        f"  Total Tax:                     Rs. {o.total_tax:>10,}",
        f"  Effective Rate:                {o.effective_rate_pct}%",
        f"New Regime:",
        f"  Taxable Income:                Rs. {n.taxable_income:>10,}",
        f"  Base Tax:                      Rs. {n.base_tax:>10,}",
        f"  Rebate 87A:                    Rs. {n.rebate_87A:>10,}",
        f"  Surcharge:                     Rs. {n.surcharge:>10,}",
        f"  Cess (4%):                     Rs. {n.cess:>10,}",
        f"  Total Tax:                     Rs. {n.total_tax:>10,}",
        f"  Effective Rate:                {n.effective_rate_pct}%",
        "",
        f"RECOMMENDATION: {rc.recommended.upper()} regime",
        f"TAX SAVINGS:    Rs. {rc.savings:,}",
        f"REASONING:      {rc.reasoning}",
    ]
    return "\n".join(lines)