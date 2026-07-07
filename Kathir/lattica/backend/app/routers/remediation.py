"""
Remediation API endpoint.

POST /scans/{scan_id}/findings/{finding_id}/remediate

Takes a finding from a completed scan and sends it to the configured
LLM provider for a deep-dive remediation analysis. The user can choose
which LLM to use (Gemini, OpenAI, Claude, Ollama) and optionally
provide their own API key.

This is the "agentic" layer — it turns scored findings into
actionable migration plans using AI.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.scan import Scan, Finding
from app.models.schemas import (
    RemediationRequest as RemediationRequestSchema,
    RemediationResponse as RemediationResponseSchema,
)
from app.services.remediation import (
    RemediationRequest,
    get_remediation,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{scan_id}/findings/{finding_id}/remediate",
    response_model=RemediationResponseSchema,
)
async def remediate_finding(
    scan_id: int,
    finding_id: int,
    payload: RemediationRequestSchema,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate an AI-powered remediation plan for a specific finding.

    The flow:
      1. Load the scan and finding from the database
      2. Build a RemediationRequest with all the context the LLM needs
      3. Call the chosen LLM provider
      4. Return the structured remediation response

    API key resolution:
      - If the user provides an api_key in the request body, use that
      - Otherwise, fall back to the ANTHROPIC_API_KEY in .env (works for Claude)
      - For Gemini/OpenAI, the user must provide their own key
      - Ollama doesn't need a key at all
    """
    # --- Step 1: Load the scan with its findings ---
    result = await db.execute(
        select(Scan)
        .options(selectinload(Scan.findings))
        .where(Scan.id == scan_id)
    )
    scan = result.scalar_one_or_none()

    if not scan:
        raise HTTPException(status_code=404, detail=f"Scan #{scan_id} not found")

    # Find the specific finding
    finding = next((f for f in scan.findings if f.id == finding_id), None)
    if not finding:
        raise HTTPException(
            status_code=404,
            detail=f"Finding #{finding_id} not found in scan #{scan_id}",
        )

    # --- Step 2: Resolve the API key and provider ---
    # Priority: user-provided key → REMEDIATION_API_KEY → ANTHROPIC_API_KEY (legacy)
    api_key = payload.api_key or settings.REMEDIATION_API_KEY or settings.ANTHROPIC_API_KEY

    # Use the app default provider if the user didn't specify one,
    # but only if the user also didn't provide a key (if they gave a key
    # they probably want to use the provider they selected in the UI)
    provider = payload.provider or settings.REMEDIATION_PROVIDER or "gemini"

    # Ollama doesn't need a key — skip validation for it
    if provider != "ollama" and not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"No API key provided for {provider}. "
                   f"Provide one in the UI settings or set REMEDIATION_API_KEY in .env",
        )

    # --- Step 3: Build the remediation request ---
    req = RemediationRequest(
        finding_type=finding.finding_type.value,
        value=finding.value,
        severity_bucket=finding.severity_bucket.value,
        hndl_risk_score=finding.hndl_risk_score,
        crypto_exposure_score=finding.crypto_exposure_score,
        domain=scan.domain,
        data_sensitivity=scan.data_sensitivity,
        retention_horizon=scan.retention_horizon,
        nist_deadline=finding.nist_deadline,
        pqc_replacement=finding.pqc_replacement,
        migration_notes=finding.migration_notes,
    )

    # --- Step 4: Call the LLM ---
    try:
        response = await get_remediation(
            req=req,
            provider_name=provider,
            api_key=api_key,
            model=payload.model,
        )
    except ValueError as e:
        # Provider configuration errors (bad provider name, missing key, etc.)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # LLM API errors (rate limits, network issues, auth failures, etc.)
        logger.error(f"Remediation failed for finding #{finding_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"LLM provider error ({provider}): {str(e)}",
        )

    return RemediationResponseSchema(
        summary=response.summary,
        risk_explanation=response.risk_explanation,
        migration_steps=response.migration_steps,
        priority=response.priority,
        provider=response.provider,
        model=response.model,
    )
