import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.privacy.session_manager import store

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class SessionStatus(BaseModel):
    session_id:     str
    exists:         bool
    active_seconds: float = None

class DeleteResponse(BaseModel):
    session_id: str
    deleted:    bool
    message:    str

@router.get("/session/{session_id}/status", response_model=SessionStatus)
def session_status(session_id: str):
    """Returns whether a session is still active."""
    import time
    session = store.get_session(session_id)
    if session is None:
        return SessionStatus(session_id=session_id, exists=False)
    active_seconds = time.time() - session["created_at"]
    return SessionStatus(
        session_id=session_id,
        exists=True,
        active_seconds=round(active_seconds, 1),
    )

@router.delete("/session/{session_id}", response_model=DeleteResponse)
def delete_session(session_id: str):
    """
    Immediately destroys all session data.
    Called by the 'Delete my data now' button in the UI.
    """
    if not store.session_exists(session_id):
        raise HTTPException(
            status_code=404,
            detail="Session not found or already deleted."
        )
    deleted = store.delete_session(session_id)
    return DeleteResponse(
        session_id=session_id,
        deleted=deleted,
        message="All your data has been permanently deleted from memory.",
    )