import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scripts.session_manager import store
from scripts.rag_engine import answer_question

router = APIRouter()

class ChatRequest(BaseModel):
    message:            str
    deduction_category: str = None  # optional filter hint

class ChatResponse(BaseModel):
    session_id: str
    question:   str
    answer:     str

@router.post("/chat/{session_id}", response_model=ChatResponse)
def chat(session_id: str, request: ChatRequest):
    """
    Answers a tax question in context of the user's uploaded documents.
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

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    answer = answer_question(
        query=request.message,
        analysis=analysis,
        session_collection=collection,
        deduction_category=request.deduction_category,
    )

    return ChatResponse(
        session_id=session_id,
        question=request.message,
        answer=answer,
    )