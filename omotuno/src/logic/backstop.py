from __future__ import annotations

from dataclasses import dataclass
import re

from src.pipeline.config import BACKSTOP_JUDGMENT_DENYLIST
from src.pipeline.types import SummaryInput


@dataclass(frozen=True)
class BackstopResult:
    passed: bool
    reason_codes: list[str]


def backstop_check_summary(payload: SummaryInput, candidate_summary: str) -> BackstopResult:
    reasons: list[str] = []
    lower = candidate_summary.lower()

    # Numeric/fact checks
    match = re.search(r"\b(\d+)\b", candidate_summary)
    if match is not None:
        reported_count = int(match.group(1))
        if reported_count != payload.total_count:
            reasons.append("COUNT_MISMATCH")
    elif payload.total_count > 0:
        reasons.append("COUNT_MISSING")

    if "." in payload.distinct_srcips and payload.distinct_srcips not in candidate_summary:
        reasons.append("IP_MISMATCH")

    if payload.first_seen not in candidate_summary or payload.last_seen not in candidate_summary:
        reasons.append("TIME_MISMATCH")

    if payload.total_count > 0 and ("no alerts" in lower or "all clear" in lower):
        reasons.append("NONZERO_BUT_CLEAR")

    # Judgment-language denylist checks
    for term in BACKSTOP_JUDGMENT_DENYLIST:
        if term in lower:
            reasons.append(f"JUDGMENT_DENYLIST:{term}")

    # De-duplicate while preserving order
    deduped = list(dict.fromkeys(reasons))
    return BackstopResult(passed=(len(deduped) == 0), reason_codes=deduped)
