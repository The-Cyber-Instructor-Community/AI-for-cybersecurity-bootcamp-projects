"""
Scan API endpoints.

POST /scans       — Create and run a new TLS scan
GET  /scans       — List all scans (summary view)
GET  /scans/{id}  — Get full scan results with findings

The scan flow:
  1. Client POSTs a domain + HNDL context (sensitivity, retention)
  2. We create a Scan record in PENDING state
  3. Run sslyze against the domain
  4. Parse findings, store them, mark scan COMPLETED
  5. Client GETs the results with scored findings

Note: Scans run synchronously within the request for now.
For a production tool we'd use a task queue (Celery, etc.),
but for the demo this keeps things simple and debuggable.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.scan import Scan, Finding, ScanStatus, FindingType
from app.models.schemas import ScanCreate, ScanResponse, ScanSummary
from app.services.scanner import scan_domain
from app.services.hndl_scorer import score_findings

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /scans — kick off a new scan
# ---------------------------------------------------------------------------

@router.post("/", response_model=ScanResponse, status_code=201)
async def create_scan(payload: ScanCreate, db: AsyncSession = Depends(get_db)):
    """
    Create a new TLS scan for the given domain.

    The scan runs inline (blocking) — the response includes
    all findings once the scan completes. Typical scan time
    is 5–15 seconds depending on the target.
    """
    # --- Step 1: Create the scan record ---
    scan = Scan(
        domain=payload.domain.strip().lower(),
        data_sensitivity=payload.data_sensitivity,
        retention_horizon=payload.retention_horizon,
        status=ScanStatus.RUNNING,
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    logger.info(f"Starting scan #{scan.id} for {scan.domain}")

    # --- Step 2: Run sslyze ---
    try:
        raw_findings = await scan_domain(scan.domain)
    except Exception as e:
        # Scan failed — record the error and return it
        scan.status = ScanStatus.FAILED
        scan.error_message = str(e)
        scan.completed_at = datetime.now(timezone.utc)
        await db.commit()

        # Must eagerly load the (empty) findings relationship before returning,
        # because async SQLAlchemy can't lazy-load during serialization.
        result = await db.execute(
            select(Scan)
            .options(selectinload(Scan.findings))
            .where(Scan.id == scan.id)
        )
        return result.scalar_one()

    # --- Step 3: Score findings through the HNDL engine ---
    # This is where raw scanner output becomes risk intelligence.
    # The scorer enriches each finding with crypto exposure scores,
    # composite HNDL risk, severity buckets, and remediation guidance.
    scored_findings = score_findings(
        raw_findings,
        data_sensitivity=scan.data_sensitivity,
        retention_horizon=scan.retention_horizon,
    )

    # --- Step 4: Store scored findings ---
    for scored in scored_findings:
        finding = Finding(
            scan_id=scan.id,
            finding_type=FindingType(scored.finding_type),
            value=scored.value,
            crypto_exposure_score=scored.crypto_exposure_score,
            hndl_risk_score=scored.hndl_risk_score,
            severity_bucket=scored.severity_bucket,
            nist_deadline=scored.nist_deadline,
            pqc_replacement=scored.pqc_replacement,
            migration_notes=scored.migration_notes,
        )
        db.add(finding)

    # --- Step 5: Mark scan as complete ---
    scan.status = ScanStatus.COMPLETED
    scan.completed_at = datetime.now(timezone.utc)
    await db.commit()

    # Reload with findings attached for the response
    result = await db.execute(
        select(Scan)
        .options(selectinload(Scan.findings))
        .where(Scan.id == scan.id)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# GET /scans — list all scans
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[ScanSummary])
async def list_scans(db: AsyncSession = Depends(get_db)):
    """List all scans, most recent first. No findings included — use GET /scans/{id} for details."""
    result = await db.execute(
        select(Scan).order_by(Scan.created_at.desc())
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# GET /scans/{id} — full scan details with findings
# ---------------------------------------------------------------------------

@router.get("/{scan_id}", response_model=ScanResponse)
async def get_scan(scan_id: int, db: AsyncSession = Depends(get_db)):
    """Get a scan with all its findings, scored and categorized."""
    result = await db.execute(
        select(Scan)
        .options(selectinload(Scan.findings))
        .where(Scan.id == scan_id)
    )
    scan = result.scalar_one_or_none()

    if not scan:
        raise HTTPException(status_code=404, detail=f"Scan #{scan_id} not found")

    return scan
