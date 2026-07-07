"""
HNDL (Harvest Now, Decrypt Later) Scoring Engine

This is Lattica's core differentiator — the reasoning layer that turns
raw TLS scan findings into actionable risk scores.

The HNDL threat model:
  An adversary records encrypted traffic TODAY, stores it, and waits for
  a quantum computer capable of breaking the encryption. If the data is
  still sensitive when that day comes, confidentiality is retroactively lost.

The scoring formula:
  HNDL Risk = S × R × E

  Where:
    S = Data Sensitivity (1–5)     — How sensitive is the data? (user-provided)
    R = Retention Horizon (1–5)    — How long must confidentiality hold? (user-provided)
    E = Crypto Exposure (1–5)      — How soon does quantum break this? (auto-derived)

  Range: 1–125

  Severity buckets:
    Critical (76–125) — Sensitive long-retention data behind weak crypto
    High     (36–75)  — Significant exposure on 2+ axes
    Medium   (11–35)  — Some risk, lower priority
    Low      (1–10)   — Minimal HNDL exposure

Why this model works:
  - A public website (S=1) using RSA-2048 (E=4) scores LOW even with
    long retention — the data isn't secret, so HNDL doesn't apply.
  - A healthcare API (S=5) using TLS 1.3 ECDHE (E=2) with 10-year
    retention (R=5) scores MEDIUM-HIGH — the crypto is decent but the
    data's value outlasts its protection timeline.
  - A financial API (S=5) using static RSA key exchange (E=4) with
    regulatory retention (R=5) scores CRITICAL — this is exactly the
    scenario HNDL attackers target.
"""

import logging
from dataclasses import dataclass

from app.services.crypto_mappings import get_crypto_profile, CryptoProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Severity bucket thresholds
# ---------------------------------------------------------------------------

SEVERITY_THRESHOLDS = [
    (76, "critical"),   # 76–125
    (36, "high"),       # 36–75
    (11, "medium"),     # 11–35
    (1,  "low"),        #  1–10
]


def _get_severity_bucket(score: float) -> str:
    """Map a composite HNDL score (1–125) to a severity bucket."""
    for threshold, bucket in SEVERITY_THRESHOLDS:
        if score >= threshold:
            return bucket
    return "low"


# ---------------------------------------------------------------------------
# Scored finding — the output of the scoring engine
# ---------------------------------------------------------------------------

@dataclass
class ScoredFinding:
    """
    A finding enriched with HNDL risk scoring and remediation guidance.
    This is what gets stored in the database.
    """
    # Original finding data
    finding_type: str
    value: str

    # Scoring
    crypto_exposure_score: int    # E: 1–5, auto-derived
    hndl_risk_score: float        # S × R × E: 1–125
    severity_bucket: str          # critical / high / medium / low

    # Remediation guidance (Tier 1 — deterministic, no AI needed)
    nist_deadline: str
    pqc_replacement: str
    migration_notes: str


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_findings(
    raw_findings: list,
    data_sensitivity: int,
    retention_horizon: int,
) -> list[ScoredFinding]:
    """
    Score a list of raw findings using the HNDL risk model.

    Takes the raw findings from the scanner and enriches each one with:
      - Crypto exposure score (from the mapping tables)
      - Composite HNDL risk score (S × R × E)
      - Severity bucket
      - NIST deadline and PQC replacement recommendation
      - Migration notes (Tier 1 deterministic guidance)

    Args:
        raw_findings: List of RawFinding objects from the scanner
        data_sensitivity: User-provided S score (1–5)
        retention_horizon: User-provided R score (1–5)

    Returns:
        List of ScoredFinding objects ready for database storage
    """
    scored = []

    for finding in raw_findings:
        # Look up this crypto primitive's quantum risk profile
        profile: CryptoProfile = get_crypto_profile(
            finding.finding_type,
            finding.value,
        )

        # Calculate composite HNDL risk score
        hndl_score = data_sensitivity * retention_horizon * profile.exposure_score

        # Determine severity bucket
        severity = _get_severity_bucket(hndl_score)

        scored.append(ScoredFinding(
            finding_type=finding.finding_type,
            value=finding.value,
            crypto_exposure_score=profile.exposure_score,
            hndl_risk_score=hndl_score,
            severity_bucket=severity,
            nist_deadline=profile.nist_deadline,
            pqc_replacement=profile.pqc_replacement,
            migration_notes=profile.migration_notes,
        ))

        logger.debug(
            f"Scored: {finding.value} → E={profile.exposure_score}, "
            f"HNDL={hndl_score} ({severity})"
        )

    # Sort by HNDL risk score descending — worst findings first
    scored.sort(key=lambda f: f.hndl_risk_score, reverse=True)

    logger.info(
        f"Scored {len(scored)} findings: "
        f"{sum(1 for f in scored if f.severity_bucket == 'critical')} critical, "
        f"{sum(1 for f in scored if f.severity_bucket == 'high')} high, "
        f"{sum(1 for f in scored if f.severity_bucket == 'medium')} medium, "
        f"{sum(1 for f in scored if f.severity_bucket == 'low')} low"
    )

    return scored
