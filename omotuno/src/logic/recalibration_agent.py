from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.pipeline.config import (
    RECALIBRATION_MIN_DIRECTIONAL_EVIDENCE,
    RECALIBRATION_THRESHOLD_STEP,
    RECALIBRATION_WINDOW_STEP_HOURS,
    SIMILARITY_THRESHOLD_MAX,
    SIMILARITY_THRESHOLD_MIN,
    WINDOW_MAX_HOURS,
    WINDOW_MIN_HOURS,
)
from src.pipeline.types import RecalibrationProposal


@dataclass
class ActiveCalibrationState:
    similarity_threshold: float
    window_hours: int


def _clamp_threshold(value: float) -> tuple[float, bool]:
    clamped = min(max(value, SIMILARITY_THRESHOLD_MIN), SIMILARITY_THRESHOLD_MAX)
    return clamped, clamped != value


def _clamp_window_hours(value: int) -> tuple[int, bool]:
    clamped = min(max(value, WINDOW_MIN_HOURS), WINDOW_MAX_HOURS)
    return clamped, clamped != value


def generate_recalibration_proposal(
    reviewed_dispositions: list[str],
    active_state: ActiveCalibrationState,
    proposal_id: str = "proposal-1",
) -> RecalibrationProposal:
    split_count = sum(1 for d in reviewed_dispositions if d == "split")
    merge_count = sum(1 for d in reviewed_dispositions if d == "merge")

    proposed_threshold = active_state.similarity_threshold
    proposed_window = active_state.window_hours
    rationale = "insufficient directional evidence from reviewed dispositions"
    risk_notes = "no change recommended"
    clamped = False

    if split_count >= RECALIBRATION_MIN_DIRECTIONAL_EVIDENCE and split_count > merge_count:
        proposed_threshold += RECALIBRATION_THRESHOLD_STEP
        proposed_window -= RECALIBRATION_WINDOW_STEP_HOURS
        rationale = "split-heavy reviewed history indicates false merges; propose stricter clustering"
        risk_notes = "stricter thresholds may increase false splits if over-applied"
    elif merge_count >= RECALIBRATION_MIN_DIRECTIONAL_EVIDENCE and merge_count > split_count:
        proposed_threshold -= RECALIBRATION_THRESHOLD_STEP
        proposed_window += RECALIBRATION_WINDOW_STEP_HOURS
        rationale = "merge-heavy reviewed history indicates false splits; propose looser clustering"
        risk_notes = "looser thresholds may increase false merges if over-applied"

    proposed_threshold, threshold_clamped = _clamp_threshold(proposed_threshold)
    proposed_window, window_clamped = _clamp_window_hours(proposed_window)
    clamped = threshold_clamped or window_clamped
    if clamped:
        rationale = f"{rationale}; clamped to configured safe bounds"

    return RecalibrationProposal(
        proposal_id=proposal_id,
        current_similarity_threshold=active_state.similarity_threshold,
        proposed_similarity_threshold=proposed_threshold,
        current_window_hours=active_state.window_hours,
        proposed_window_hours=proposed_window,
        split_count=split_count,
        merge_count=merge_count,
        rationale=rationale,
        risk_notes=risk_notes,
        clamped=clamped,
        status="pending_approval",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def approve_proposal(
    proposal: RecalibrationProposal,
    reviewed_by: str,
    reviewed_at: datetime,
    active_state: ActiveCalibrationState,
) -> RecalibrationProposal:
    if not reviewed_by:
        raise ValueError("reviewed_by is required")
    if proposal.status != "pending_approval":
        raise ValueError("only pending proposals can be approved")

    active_state.similarity_threshold = proposal.proposed_similarity_threshold
    active_state.window_hours = proposal.proposed_window_hours
    return RecalibrationProposal(
        proposal_id=proposal.proposal_id,
        current_similarity_threshold=proposal.current_similarity_threshold,
        proposed_similarity_threshold=proposal.proposed_similarity_threshold,
        current_window_hours=proposal.current_window_hours,
        proposed_window_hours=proposal.proposed_window_hours,
        split_count=proposal.split_count,
        merge_count=proposal.merge_count,
        rationale=proposal.rationale,
        risk_notes=proposal.risk_notes,
        clamped=proposal.clamped,
        status="approved",
        created_at=proposal.created_at,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at.isoformat(),
    )


def reject_proposal(
    proposal: RecalibrationProposal,
    reviewed_by: str,
    reviewed_at: datetime,
    reason: str | None = None,
) -> RecalibrationProposal:
    if not reviewed_by:
        raise ValueError("reviewed_by is required")
    if proposal.status != "pending_approval":
        raise ValueError("only pending proposals can be rejected")

    return RecalibrationProposal(
        proposal_id=proposal.proposal_id,
        current_similarity_threshold=proposal.current_similarity_threshold,
        proposed_similarity_threshold=proposal.proposed_similarity_threshold,
        current_window_hours=proposal.current_window_hours,
        proposed_window_hours=proposal.proposed_window_hours,
        split_count=proposal.split_count,
        merge_count=proposal.merge_count,
        rationale=proposal.rationale,
        risk_notes=proposal.risk_notes,
        clamped=proposal.clamped,
        status="rejected",
        created_at=proposal.created_at,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at.isoformat(),
        rejection_reason=reason,
    )
