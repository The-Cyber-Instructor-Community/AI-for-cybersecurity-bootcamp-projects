from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.logic.recalibration_agent import (
    ActiveCalibrationState,
    approve_proposal,
    generate_recalibration_proposal,
    reject_proposal,
)


def test_recalibration_direction_and_pending_default() -> None:
    state = ActiveCalibrationState(similarity_threshold=0.82, window_hours=12)

    split_heavy = generate_recalibration_proposal(["split", "split", "confirm"], state, proposal_id="p1")
    assert split_heavy.status == "pending_approval"
    assert split_heavy.proposed_similarity_threshold >= split_heavy.current_similarity_threshold
    assert split_heavy.proposed_window_hours <= split_heavy.current_window_hours
    assert state.similarity_threshold == 0.82
    assert state.window_hours == 12

    merge_heavy = generate_recalibration_proposal(["merge", "merge", "dismiss"], state, proposal_id="p2")
    assert merge_heavy.proposed_similarity_threshold <= merge_heavy.current_similarity_threshold
    assert merge_heavy.proposed_window_hours >= merge_heavy.current_window_hours


def test_recalibration_clamp_and_approval_gate() -> None:
    near_max = ActiveCalibrationState(similarity_threshold=0.95, window_hours=1)
    proposal = generate_recalibration_proposal(["split", "split", "split"], near_max, proposal_id="p3")
    assert proposal.clamped is True

    state = ActiveCalibrationState(similarity_threshold=0.82, window_hours=12)
    p = generate_recalibration_proposal(["merge", "merge"], state, proposal_id="p4")
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    approved = approve_proposal(p, reviewed_by="analyst@example.com", reviewed_at=now, active_state=state)
    assert approved.status == "approved"
    assert state.similarity_threshold == p.proposed_similarity_threshold
    assert state.window_hours == p.proposed_window_hours

    with pytest.raises(ValueError):
        reject_proposal(approved, reviewed_by="analyst@example.com", reviewed_at=now, reason="nope")


def test_recalibration_reject_does_not_apply() -> None:
    state = ActiveCalibrationState(similarity_threshold=0.82, window_hours=12)
    p = generate_recalibration_proposal(["split", "split"], state, proposal_id="p5")
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    rejected = reject_proposal(p, reviewed_by="analyst@example.com", reviewed_at=now, reason="insufficient evidence")
    assert rejected.status == "rejected"
    assert state.similarity_threshold == 0.82
    assert state.window_hours == 12
