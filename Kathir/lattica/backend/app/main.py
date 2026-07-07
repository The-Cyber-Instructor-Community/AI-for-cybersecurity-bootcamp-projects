"""
Lattica — Post-Quantum Cryptography Readiness Tool

Main FastAPI application entry point.
Scans TLS endpoints for quantum-vulnerable cryptography,
scores findings using the HNDL risk model, and provides
AI-powered remediation guidance.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.routers import scans, remediation

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Lattica",
    description="Post-Quantum Cryptography Readiness Tool — scan, score, remediate.",
    version="0.1.0",
)

# Allow the React frontend to talk to the API during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(scans.router, prefix="/scans", tags=["scans"])
app.include_router(remediation.router, prefix="/scans", tags=["remediation"])


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    """Create database tables on first run."""
    await init_db()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Simple liveness probe."""
    return {"status": "ok", "service": "lattica"}
