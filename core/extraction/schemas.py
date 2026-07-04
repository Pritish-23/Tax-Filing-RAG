from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import date as date_type
from enum import Enum

# ── enums ─────────────────────────────────────────────────────────────────────

class TransactionCategory(str, Enum):
    SALARY      = "SALARY"
    RENT        = "RENT"
    INVESTMENT  = "INVESTMENT"
    INSURANCE   = "INSURANCE"
    EXPENSE     = "EXPENSE"
    OTHER       = "OTHER"

class InvestmentTag(str, Enum):
    LIC_80C       = "80C_LIC"
    PPF_80C       = "80C_PPF"
    ELSS_80C      = "80C_ELSS"
    SELF_80D      = "80D_SELF"
    PARENTS_80D   = "80D_PARENTS"
    HRA_RENT      = "HRA_RENT"
    NONE          = ""

# ── Form 16 extraction schema ─────────────────────────────────────────────────

class Form16Data(BaseModel):
    """
    Structured fields extracted from an uploaded Form 16 PDF.
    All monetary fields are in whole Rupees (no paise).
    """
    employee_name:        str
    pan_masked:            str = Field(description="PAN with middle digits masked, e.g. ABCPS****A")
    employer_name:         str
    employer_tan:          str
    assessment_year:       str = Field(description="e.g. '2026-27'")

    gross_salary:           int = Field(ge=0)
    basic_salary:           int = Field(ge=0)
    hra_received:            int = Field(ge=0)
    hra_exemption_claimed:  int = Field(ge=0, default=0)

    standard_deduction:     int = Field(ge=0)
    deduction_80C_claimed:  int = Field(ge=0, default=0)
    deduction_80D_claimed:  int = Field(ge=0, default=0)

    net_taxable_income:     int = Field(ge=0)
    tds_deducted:            int = Field(ge=0)

    extraction_confidence:  float = Field(ge=0.0, le=1.0, default=1.0)

    @field_validator("pan_masked")
    @classmethod
    def mask_pan(cls, v: str) -> str:
        """Ensure PAN is never stored in full — privacy by design even within the schema."""
        if len(v) == 10 and "*" not in v:
            return v[:5] + "****" + v[-1]
        return v


# ── bank transaction schema ───────────────────────────────────────────────────

class BankTransaction(BaseModel):
    txn_date:     date_type
    description:  str
    debit:        Optional[int] = None
    credit:       Optional[int] = None
    category:     TransactionCategory
    tag:          InvestmentTag = InvestmentTag.NONE


# ── investment summary (derived from bank transactions) ──────────────────────

class InvestmentSummary(BaseModel):
    """
    Aggregated from all tagged bank transactions.
    This is what gets matched against 80C/80D limits in Phase 5.
    """
    total_lic_premium:      int = 0
    total_ppf_deposit:       int = 0
    total_elss_investment:  int = 0
    total_80C_raw:           int = 0   # sum before applying 1.5L cap

    total_self_health_premium:    int = 0
    total_parents_health_premium: int = 0

    total_rent_paid_annual:  int = 0
    rent_transaction_count:  int = 0


# ── combined extracted financials (feeds Phase 4 session state) ──────────────

class ExtractedFinancials(BaseModel):
    """
    The complete in-memory representation of a user's session.
    This object lives ONLY in the ephemeral session state (Phase 4) —
    never serialized to disk.
    """
    session_id:          str
    form16:               Form16Data
    investments:          InvestmentSummary
    raw_transactions:    list[BankTransaction] = Field(default_factory=list)

    class Config:
        # Prevents accidental extra fields from silently entering the schema
        extra = "forbid"