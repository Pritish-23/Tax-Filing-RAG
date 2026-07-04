import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from app.routers import upload, analysis, chat, session

# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Tax Filing RAG Assistant",
    description="Privacy-first Indian income tax filing assistant for salaried individuals",
    version="1.0.0",
)

# ── CORS (allows Streamlit frontend to talk to FastAPI) ───────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit default port
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── routers ───────────────────────────────────────────────────────────────────

app.include_router(upload.router,   prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(chat.router,     prefix="/api")
app.include_router(session.router,  prefix="/api")

# ── health check ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    from scripts.session_manager import store
    return {
        "status":          "ok",
        "active_sessions": store.active_session_count(),
    }

@app.get("/")
def root():
    return {"message": "Tax Filing RAG Assistant API", "docs": "/docs"}