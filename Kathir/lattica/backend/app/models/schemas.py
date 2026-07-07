"""
Pydantic schemas — define the shape of API requests and responses.

These are separate from the SQLAlchemy models (scan.py) on purpose:
  - SQLAlchemy models define the database structure
  - Pydantic schemas define the API contract

This separation lets us control exactly what data goes in and out
without leaking internal database details to the client.
"""

from datetime import datetime
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas — what the client sends us
# ---------------------------------------------------------------------------

class ScanCreate(BaseModel):
    """POST /scans — kick off a new TLS scan."""
    domain: str = Field(
        ...,
        description="Target domain to scan (e.g., 'example.com')",
        examples=["example.com", "api.stripe.com"],
    )
    # HNDL context: user declares how sensitive their data is
    data_sensitivity: int = Field(
        default=3,
        ge=1, le=5,
        description="How sensitive is the data flowing over this connection? 1=public, 5=financial/health",
    )
    retention_horizon: int = Field(
        default=3,
        ge=1, le=5,
        description="How long must this data stay confidential? 1=ephemeral, 5=7+ year regulatory retention",
    )


# ---------------------------------------------------------------------------
# Response schemas — what we send back to the client
# ---------------------------------------------------------------------------

class FindingResponse(BaseModel):
    """A single crypto finding within a scan result."""
    id: int
    finding_type: str
    value: str
    crypto_exposure_score: int
    hndl_risk_score: float
    severity_bucket: str
    nist_deadline: str | None
    pqc_replacement: str | None
    migration_notes: str | None

    model_config = {"from_attributes": True}


class ScanResponse(BaseModel):
    """Full scan result with all findings."""
    id: int
    domain: str
    data_sensitivity: int
    retention_horizon: int
    status: str
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    findings: list[FindingResponse] = []

    model_config = {"from_attributes": True}


class ScanSummary(BaseModel):
    """Lightweight scan info for list views (no findings included)."""
    id: int
    domain: str
    status: str
    data_sensitivity: int
    retention_horizon: int
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Remediation schemas — AI-powered deep dive on a finding
# ---------------------------------------------------------------------------

class RemediationRequest(BaseModel):
    """POST /scans/{id}/findings/{id}/remediate — request body."""
    # LLM provider selection
    provider: str = Field(
        default="gemini",
        description="LLM provider to use: gemini, openai, claude, or ollama",
    )
    api_key: str = Field(
        default="",
        description="API key for the LLM provider (not needed for Ollama). "
                    "Falls back to the app-level key from .env if not provided.",
    )
    model: str = Field(
        default="",
        description="Optional model override (each provider has a sensible default)",
    )


class RemediationResponse(BaseModel):
    """Structured AI remediation response."""
    summary: str             # 1–2 sentence executive summary
    risk_explanation: str    # Why this finding matters for HNDL
    migration_steps: str     # Step-by-step migration plan
    priority: str            # Recommended priority and timeline
    provider: str            # Which LLM generated this (transparency)
    model: str               # Specific model used
