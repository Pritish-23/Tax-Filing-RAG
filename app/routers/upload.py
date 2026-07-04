import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.extraction.extract_documents import extract_all
from core.privacy.session_manager import store
from core.reasoning.deduction_engine import run_tax_analysis

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from pydantic import BaseModel

router = APIRouter()

class UploadResponse(BaseModel):
    session_id:       str
    employee_name:    str
    assessment_year:  str
    gross_salary:     int
    message:          str

@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    form16:                 UploadFile = File(...),
    bank_statement:         UploadFile = File(...),
    is_metro:               bool = Form(False),
    parents_senior_citizen: bool = Form(False),
):
    """
    Accepts Form 16 PDF and bank statement CSV.
    Extracts financials, creates ephemeral session, runs tax analysis.
    Documents are processed in memory — never written to disk.
    """

    # Validate file types
    if not form16.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Form 16 must be a PDF file")
    if not bank_statement.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Bank statement must be a CSV file")

    try:
        # Read files into memory buffers — never touch disk
        form16_bytes    = await form16.read()
        bank_bytes      = await bank_statement.read()

        form16_buffer   = io.BytesIO(form16_bytes)
        bank_buffer     = io.BytesIO(bank_bytes)

        # Extract financials
        financials = extract_all(
            form16_source=form16_buffer,
            bank_statement_source=bank_buffer,
            session_id="pending",
        )

        # Create ephemeral session
        session_id = store.create_session(financials)

        # Update session_id on the financials object
        financials.session_id = session_id

        # Run tax analysis and store in session
        analysis = run_tax_analysis(
            financials,
            is_metro=is_metro,
            parents_senior_citizen=parents_senior_citizen,
        )

        # Store analysis in session for later retrieval
        session = store.get_session(session_id)
        session["analysis"]                = analysis
        session["is_metro"]                = is_metro
        session["parents_senior_citizen"]  = parents_senior_citizen

        return UploadResponse(
            session_id=session_id,
            employee_name=financials.form16.employee_name,
            assessment_year=financials.form16.assessment_year,
            gross_salary=financials.form16.gross_salary,
            message="Documents processed successfully. Your data is stored in memory only.",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")