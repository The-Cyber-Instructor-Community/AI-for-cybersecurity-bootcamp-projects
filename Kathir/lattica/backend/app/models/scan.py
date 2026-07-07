"""
Database models for scans and findings.

A Scan represents one TLS scan of a target domain.
Each scan produces multiple Findings — one per cipher suite,
protocol version, certificate property, or key exchange method
that sslyze reports.

The HNDL risk model scores each finding on three axes:
  - Data Sensitivity (S): user-provided, how sensitive is the data
  - Retention Horizon (R): user-provided, how long confidentiality must hold
  - Crypto Exposure (E): auto-derived from the crypto primitive's quantum resistance

  HNDL Risk = S × R × E  (range 1–125)
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Text, Enum as SAEnum
)
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ScanStatus(str, enum.Enum):
    """Tracks the lifecycle of a scan."""
    PENDING = "pending"        # Queued but not yet started
    RUNNING = "running"        # sslyze is actively scanning
    COMPLETED = "completed"    # Scan finished successfully
    FAILED = "failed"          # Scan encountered an error


class SeverityBucket(str, enum.Enum):
    """
    HNDL risk severity buckets.
    Derived from the composite score (S × R × E).
    """
    CRITICAL = "critical"   # 76–125: sensitive long-retention data + weak crypto
    HIGH = "high"           # 36–75:  significant exposure on 2+ axes
    MEDIUM = "medium"       # 11–35:  some risk, lower priority
    LOW = "low"             #  1–10:  minimal HNDL exposure


class FindingType(str, enum.Enum):
    """Categories of TLS findings from sslyze."""
    CIPHER_SUITE = "cipher_suite"       # e.g., TLS_RSA_WITH_AES_128_CBC_SHA
    PROTOCOL = "protocol"               # e.g., TLS 1.0, TLS 1.2
    CERTIFICATE = "certificate"         # e.g., RSA-2048 signature
    KEY_EXCHANGE = "key_exchange"        # e.g., ECDHE, RSA key exchange


# ---------------------------------------------------------------------------
# Scan model — one row per domain scanned
# ---------------------------------------------------------------------------

class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Target domain to scan (e.g., "example.com")
    domain = Column(String(255), nullable=False, index=True)

    # User-provided HNDL context — these are subjective inputs
    # that make the tool a risk modeler, not just a scanner
    data_sensitivity = Column(Integer, nullable=False, default=3)    # 1–5 scale
    retention_horizon = Column(Integer, nullable=False, default=3)   # 1–5 scale

    # Scan metadata
    status = Column(SAEnum(ScanStatus), nullable=False, default=ScanStatus.PENDING)
    error_message = Column(Text, nullable=True)  # Populated if status == FAILED
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)

    # One scan → many findings
    findings = relationship("Finding", back_populates="scan", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Scan id={self.id} domain={self.domain} status={self.status}>"


# ---------------------------------------------------------------------------
# Finding model — one row per crypto finding within a scan
# ---------------------------------------------------------------------------

class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)

    # What kind of finding this is (cipher, protocol, cert, key exchange)
    finding_type = Column(SAEnum(FindingType), nullable=False)

    # The actual value found (e.g., "TLS_RSA_WITH_AES_256_GCM_SHA384")
    value = Column(String(512), nullable=False)

    # Crypto Exposure score — auto-derived from the value
    # How soon this crypto primitive breaks under quantum computing
    # 1 = PQC-ready, 5 = RSA-1024 (already weak)
    crypto_exposure_score = Column(Integer, nullable=False, default=3)

    # Composite HNDL risk score = data_sensitivity × retention_horizon × crypto_exposure
    # Range: 1–125, computed at scan time using the Scan's S and R values
    hndl_risk_score = Column(Float, nullable=False, default=0.0)

    # Which severity bucket this falls into (derived from hndl_risk_score)
    severity_bucket = Column(SAEnum(SeverityBucket), nullable=False, default=SeverityBucket.MEDIUM)

    # NIST migration timeline — when this primitive is deprecated / disallowed
    nist_deadline = Column(String(50), nullable=True)  # e.g., "Deprecated 2030, Disallowed 2035"

    # Deterministic remediation: the PQC algorithm that should replace this
    pqc_replacement = Column(String(255), nullable=True)  # e.g., "ML-KEM-768 (FIPS 203)"

    # Brief migration note (Tier 1 deterministic guidance)
    migration_notes = Column(Text, nullable=True)

    # Back-reference to parent scan
    scan = relationship("Scan", back_populates="findings")

    def __repr__(self):
        return f"<Finding id={self.id} type={self.finding_type} value={self.value} hndl={self.hndl_risk_score}>"
