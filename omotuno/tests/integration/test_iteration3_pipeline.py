from __future__ import annotations

from datetime import datetime, timezone

from src.pipeline.run_iteration3 import (
    approve_recalibration_proposal,
    get_active_calibration_state,
    reject_recalibration_proposal,
    run_iteration3_from_records,
)
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.store.review_store import InMemoryReviewStore


def _drift_injected_records() -> list[dict]:
    records = generate_synthetic_wazuh_ssh_alerts()
    # Keep deterministic embedding seed stable (same "for ... from ..."), but inject strong semantic drift in tail text.
    for idx in range(110, 150):
        records[idx]["full_log"] = (
            f"sshd: Failed password for root from 10.0.0.10 port {2200 + idx} ssh2 "
            "suspicious lateral movement command-and-control beacon token exfiltration persistence"
        )
    return records


def test_iteration3_discriminates_coherent_vs_drifted_clusters() -> None:
    review_store = InMemoryReviewStore()
    review_store.log_action("split", "c-a", {"reviewed_by": "analyst@example.com"})
    review_store.log_action("split", "c-b", {"reviewed_by": "analyst@example.com"})
    review_store.log_action("merge", "c-c", {"reviewed_by": "analyst@example.com"})

    coherent = run_iteration3_from_records(
        records=generate_synthetic_wazuh_ssh_alerts(),
        use_live_bedrock=False,
        use_sqlite_suppression=False,
        review_store=review_store,
    )
    drifted = run_iteration3_from_records(
        records=_drift_injected_records(),
        use_live_bedrock=False,
        use_sqlite_suppression=False,
        review_store=review_store,
    )

    assert coherent.raw_alert_count == 200
    assert drifted.raw_alert_count == 200
    assert len(coherent.drifted_clusters) == 0
    assert len(drifted.drifted_clusters) >= 1
    assert len(drifted.singleton_escalations) >= 1

    proposal = drifted.recalibration_proposals[0]
    assert proposal.status == "pending_approval"
    assert proposal.split_count >= 2
    assert proposal.merge_count >= 1


def test_iteration3_approval_gate_transitions() -> None:
    records = generate_synthetic_wazuh_ssh_alerts()
    review_store = InMemoryReviewStore()
    review_store.log_action("merge", "c-a", {"reviewed_by": "analyst@example.com"})
    review_store.log_action("merge", "c-b", {"reviewed_by": "analyst@example.com"})

    result = run_iteration3_from_records(records=records, review_store=review_store)
    proposal = result.recalibration_proposals[0]
    state = get_active_calibration_state()
    old_threshold = state.similarity_threshold
    old_window = state.window_hours
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    rejected = reject_recalibration_proposal(
        proposal=proposal,
        reviewed_by="analyst@example.com",
        reviewed_at=now,
        reason="not enough evidence",
        review_store=review_store,
    )
    assert rejected.status == "rejected"
    assert state.similarity_threshold == old_threshold
    assert state.window_hours == old_window

    proposal2 = run_iteration3_from_records(records=records, review_store=review_store).recalibration_proposals[0]
    approved = approve_recalibration_proposal(
        proposal=proposal2,
        reviewed_by="analyst@example.com",
        reviewed_at=now,
        review_store=review_store,
    )
    assert approved.status == "approved"
    assert state.similarity_threshold == proposal2.proposed_similarity_threshold
    assert state.window_hours == proposal2.proposed_window_hours
