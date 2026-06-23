import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# ── config ────────────────────────────────────────────────────────────────────

CONSTANTS_PATH = Path("data/tax_constants.yaml")

# ── data classes ──────────────────────────────────────────────────────────────

@dataclass
class DeductionSummary:
    """Deductions applicable under the old regime."""
    standard_deduction: int
    deduction_80C:       int   # capped at 1.5L
    deduction_80D:       int   # capped per limits
    hra_exemption:       int
    total:               int


@dataclass
class RegimeResult:
    """Tax computation result for one regime."""
    regime:              str   # "old" or "new"
    gross_salary:        int
    total_deductions:    int
    taxable_income:      int
    base_tax:            int
    rebate_87A:          int
    tax_after_rebate:    int
    surcharge:           int
    tax_after_surcharge: int
    cess:                int
    total_tax:           int
    effective_rate_pct:  float


@dataclass
class RegimeComparison:
    """Side-by-side comparison of both regimes."""
    old_regime:      RegimeResult
    new_regime:      RegimeResult
    recommended:     str          # "old", "new", or "borderline"
    savings:         int          # how much cheaper the recommended regime is
    reasoning:       str          # plain-text explanation seed for the LLM


# ── constants loader ──────────────────────────────────────────────────────────

def load_constants(ay: str) -> dict:
    with open(CONSTANTS_PATH, "r") as f:
        all_constants = yaml.safe_load(f)
    if ay not in all_constants["assessment_years"]:
        raise ValueError(f"AY {ay} not found in tax_constants.yaml")
    return all_constants["assessment_years"][ay]


# ── slab tax computation ──────────────────────────────────────────────────────

def compute_slab_tax(taxable_income: int, slabs: list[dict]) -> int:
    """
    Computes tax using progressive slab rates.
    Each slab dict has 'upto' (None = no upper limit) and 'rate'.
    """
    tax       = 0
    prev_upto = 0

    for slab in slabs:
        upto = slab["upto"]
        rate = slab["rate"]

        if upto is None:
            # topmost slab — no upper limit
            if taxable_income > prev_upto:
                tax += (taxable_income - prev_upto) * rate
            break
        else:
            slab_top = upto
            if taxable_income <= prev_upto:
                break
            taxable_in_slab = min(taxable_income, slab_top) - prev_upto
            tax += taxable_in_slab * rate
            prev_upto = slab_top

    return int(tax)


# ── surcharge computation ─────────────────────────────────────────────────────

def compute_surcharge(base_tax: int, taxable_income: int, surcharge_slabs: list[dict]) -> int:
    """
    Surcharge is levied on the base tax (not on income).
    Applies the highest applicable rate.
    Marginal relief is NOT implemented here for simplicity —
    flagged as a known limitation in the README.
    """
    applicable_rate = 0.0
    for slab in sorted(surcharge_slabs, key=lambda x: x["above"]):
        if taxable_income > slab["above"]:
            applicable_rate = slab["rate"]
    return int(base_tax * applicable_rate)


# ── rebate 87A ────────────────────────────────────────────────────────────────

def compute_rebate_87A(taxable_income: int, base_tax: int, rebate_config: dict) -> int:
    """
    Section 87A rebate: if taxable income <= threshold,
    rebate = min(base_tax, max_rebate).
    """
    if taxable_income <= rebate_config["max_income"]:
        return min(base_tax, rebate_config["max_rebate"])
    return 0


# ── single regime calculator ──────────────────────────────────────────────────

def compute_regime_tax(
    regime_name:      str,
    gross_salary:     int,
    deductions:       DeductionSummary,
    constants:        dict,
) -> RegimeResult:
    """
    Computes full tax liability for one regime.
    For the new regime, deductions are not allowed (except standard deduction).
    """
    regime_constants = constants[f"{regime_name}_regime"]
    std_deduction    = constants["standard_deduction"][f"{regime_name}_regime"]

    # Deductions allowed per regime
    if regime_name == "new":
        total_deductions = std_deduction  # only standard deduction in new regime
    else:
        total_deductions = deductions.total  # all deductions in old regime

    # HRA exemption not allowed under new regime (Section 115BAC)
    if regime_name == "new":
        taxable_income = max(0, gross_salary - total_deductions)
    else:
        taxable_income = max(0, gross_salary - deductions.hra_exemption - total_deductions)

    # Slab tax
    base_tax = compute_slab_tax(taxable_income, regime_constants["slabs"])

    # Rebate 87A
    rebate = compute_rebate_87A(taxable_income, base_tax, regime_constants["rebate_87A"])
    tax_after_rebate = max(0, base_tax - rebate)

    # Surcharge
    surcharge = compute_surcharge(tax_after_rebate, taxable_income, regime_constants["surcharge"])
    tax_after_surcharge = tax_after_rebate + surcharge

    # Health and Education Cess (4%)
    cess      = int(tax_after_surcharge * regime_constants["health_education_cess"])
    total_tax = tax_after_surcharge + cess

    effective_rate = round((total_tax / gross_salary) * 100, 2) if gross_salary > 0 else 0.0

    return RegimeResult(
        regime=regime_name,
        gross_salary=gross_salary,
        total_deductions=total_deductions,
        taxable_income=taxable_income,
        base_tax=base_tax,
        rebate_87A=rebate,
        tax_after_rebate=tax_after_rebate,
        surcharge=surcharge,
        tax_after_surcharge=tax_after_surcharge,
        cess=cess,
        total_tax=total_tax,
        effective_rate_pct=effective_rate,
    )


# ── deduction builder ─────────────────────────────────────────────────────────

def build_deductions(
    ay:                    str,
    gross_salary:          int,
    basic_salary:          int,
    hra_received:          int,
    rent_paid_annual:      int,
    is_metro:              bool,
    raw_80C:               int,
    self_health_premium:   int,
    parents_health_premium: int,
    parents_senior_citizen: bool,
    constants:             dict,
) -> DeductionSummary:
    """
    Applies statutory caps to all deductions and computes HRA exemption.
    This is the authoritative deduction computation — Phase 5 LLM
    reads the output of this, never recomputes it.
    """
    limits = constants["deduction_limits"]

    # Standard deduction (old regime value used here — new regime handled in compute_regime_tax)
    std_deduction = constants["standard_deduction"]["old_regime"]

    # 80C cap
    deduction_80C = min(raw_80C, limits["section_80C"]["max_limit"])

    # 80D caps
    self_limit   = (limits["section_80D"]["self_spouse_children"]["senior_citizen_limit"]
                    if False  # self is never senior citizen in our scope
                    else limits["section_80D"]["self_spouse_children"]["limit"])
    parent_limit = (limits["section_80D"]["parents"]["senior_citizen_limit"]
                    if parents_senior_citizen
                    else limits["section_80D"]["parents"]["limit"])

    deduction_80D = min(self_health_premium, self_limit) + min(parents_health_premium, parent_limit)

    # HRA exemption (Rule 2A)
    hra_exemption = 0
    if rent_paid_annual > 0 and hra_received > 0:
        metro_pct    = limits["hra"]["metro_salary_percent"]    if is_metro else limits["hra"]["non_metro_salary_percent"]
        hra_exemption = int(min(
            hra_received,
            metro_pct * basic_salary,
            rent_paid_annual - 0.10 * basic_salary,
        ))
        hra_exemption = max(0, hra_exemption)

    total = std_deduction + deduction_80C + deduction_80D

    return DeductionSummary(
        standard_deduction=std_deduction,
        deduction_80C=deduction_80C,
        deduction_80D=deduction_80D,
        hra_exemption=hra_exemption,
        total=total,
    )


# ── regime comparison ─────────────────────────────────────────────────────────

def compare_regimes(
    gross_salary:           int,
    basic_salary:           int,
    hra_received:           int,
    rent_paid_annual:       int,
    is_metro:               bool,
    raw_80C:                int,
    self_health_premium:    int,
    parents_health_premium: int,
    parents_senior_citizen: bool,
    ay:                     str,
) -> RegimeComparison:
    """
    Main entry point for Phase 5 regime comparison.
    Returns a full side-by-side comparison with recommendation and plain-text reasoning.
    """
    constants  = load_constants(ay)
    deductions = build_deductions(
        ay=ay,
        gross_salary=gross_salary,
        basic_salary=basic_salary,
        hra_received=hra_received,
        rent_paid_annual=rent_paid_annual,
        is_metro=is_metro,
        raw_80C=raw_80C,
        self_health_premium=self_health_premium,
        parents_health_premium=parents_health_premium,
        parents_senior_citizen=parents_senior_citizen,
        constants=constants,
    )

    old = compute_regime_tax("old", gross_salary, deductions, constants)
    new = compute_regime_tax("new", gross_salary, deductions, constants)

    # Recommendation
    BORDERLINE_THRESHOLD = 5000  # less than Rs 5k difference → borderline
    diff = abs(old.total_tax - new.total_tax)

    if diff <= BORDERLINE_THRESHOLD:
        recommended = "borderline"
        savings     = diff
    elif old.total_tax < new.total_tax:
        recommended = "old"
        savings     = new.total_tax - old.total_tax
    else:
        recommended = "new"
        savings     = old.total_tax - new.total_tax

    # Plain-text reasoning seed (LLM expands this in Phase 5 Layer 3)
    reasoning = _build_reasoning(old, new, deductions, recommended, savings)

    return RegimeComparison(
        old_regime=old,
        new_regime=new,
        recommended=recommended,
        savings=savings,
        reasoning=reasoning,
    )


def _build_reasoning(
    old: RegimeResult,
    new: RegimeResult,
    deductions: DeductionSummary,
    recommended: str,
    savings: int,
) -> str:
    lines = [
        f"Old regime: taxable income Rs {old.taxable_income:,}, total tax Rs {old.total_tax:,} (effective rate {old.effective_rate_pct}%)",
        f"New regime: taxable income Rs {new.taxable_income:,}, total tax Rs {new.total_tax:,} (effective rate {new.effective_rate_pct}%)",
        f"Deductions under old regime: standard Rs {deductions.standard_deduction:,} + 80C Rs {deductions.deduction_80C:,} + 80D Rs {deductions.deduction_80D:,} + HRA Rs {deductions.hra_exemption:,} = total Rs {deductions.total + deductions.hra_exemption:,}",
        f"Recommendation: {recommended.upper()} regime saves Rs {savings:,}",
    ]
    return "\n".join(lines)