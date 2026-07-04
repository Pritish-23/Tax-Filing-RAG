import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.privacy.session_manager import store
from core.reasoning.rag_engine import explain_regime_comparison

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class RegimeResult(BaseModel):
    regime:              str
    taxable_income:      int
    total_tax:           int
    effective_rate_pct:  float
    rebate_87A:          int
    surcharge:           int
    cess:                int

class DeductionBreakdown(BaseModel):
    standard_deduction:  int
    deduction_80C:       int
    deduction_80D:       int
    hra_exemption:       int
    total:               int
    unused_80C_capacity: int

class AnalysisResponse(BaseModel):
    session_id:          str
    assessment_year:     str
    recommended_regime:  str
    savings:             int
    old_regime:          RegimeResult
    new_regime:          RegimeResult
    deductions:          DeductionBreakdown
    explanation:         str

@router.get("/analysis/{session_id}", response_model=AnalysisResponse)
def get_analysis(session_id: str):
    """
    Returns the full regime comparison and deduction breakdown for a session.
    """
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found or expired. Please re-upload your documents."
        )

    analysis   = session.get("analysis")
    collection = store.get_collection(session_id)

    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found for this session.")

    rc = analysis.regime_comparison
    d  = analysis.deduction_detail

    # Generate LLM explanation
    explanation = explain_regime_comparison(analysis, collection)

    return AnalysisResponse(
        session_id=session_id,
        assessment_year=d.assessment_year,
        recommended_regime=rc.recommended,
        savings=rc.savings,
        old_regime=RegimeResult(
            regime="old",
            taxable_income=rc.old_regime.taxable_income,
            total_tax=rc.old_regime.total_tax,
            effective_rate_pct=rc.old_regime.effective_rate_pct,
            rebate_87A=rc.old_regime.rebate_87A,
            surcharge=rc.old_regime.surcharge,
            cess=rc.old_regime.cess,
        ),
        new_regime=RegimeResult(
            regime="new",
            taxable_income=rc.new_regime.taxable_income,
            total_tax=rc.new_regime.total_tax,
            effective_rate_pct=rc.new_regime.effective_rate_pct,
            rebate_87A=rc.new_regime.rebate_87A,
            surcharge=rc.new_regime.surcharge,
            cess=rc.new_regime.cess,
        ),
        deductions=DeductionBreakdown(
            standard_deduction=d.standard_deduction,
            deduction_80C=d.eligible_80C,
            deduction_80D=d.eligible_80D,
            hra_exemption=d.hra_exemption,
            total=d.total_old_regime_deductions,
            unused_80C_capacity=d.unused_80C_capacity,
        ),
        explanation=explanation,
    )