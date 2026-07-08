from __future__ import annotations

from datetime import datetime

from src.logic.drift_agent import evaluate_cluster_drift
from src.logic.recalibration_agent import (
    ActiveCalibrationState,
    approve_proposal,
    generate_recalibration_proposal,
    reject_proposal,
)
from src.logic.review_gate import build_review_queue
from src.logic.singleton_escalation_agent import classify_singleton
from src.pipeline.config import SIMILARITY_THRESHOLD, WINDOW
from src.pipeline.run_iteration2 import run_iteration2_from_json, run_iteration2_from_records
from src.pipeline.types import Iteration3Result, RecalibrationProposal
from src.store.review_store import InMemoryReviewStore


_ACTIVE_CALIBRATION_STATE = ActiveCalibrationState(
    similarity_threshold=SIMILARITY_THRESHOLD,
    window_hours=int(WINDOW.total_seconds() // 3600),
)


def get_active_calibration_state() -> ActiveCalibrationState:
    return _ACTIVE_CALIBRATION_STATE



def _reviewed_dispositions_from_store(review_store) -> list[str]:
    if hasattr(review_store, "reviewed_dispositions"):
        return review_store.reviewed_dispositions()
    return []


def run_iteration3_from_records(
    records: list[dict],
    use_live_bedrock: bool = False,
    use_sqlite_suppression: bool = False,
    review_store=None,
    active_calibration_state: ActiveCalibrationState | None = None,
) -> Iteration3Result:
    state = active_calibration_state or _ACTIVE_CALIBRATION_STATE
    base = run_iteration2_from_records(
        records=records,
        use_live_bedrock=use_live_bedrock,
        use_sqlite_suppression=use_sqlite_suppression,
    )

    drifted_clusters = []
    singleton_escalations = []

    for cluster in base.clusters:
        drift = evaluate_cluster_drift(cluster)
        cluster.drift_detected = drift.drift_detected
        cluster.drift_score = drift.drift_score
        cluster.drift_reason = drift.reason
        cluster.drift_evidence = drift.evidence
        if drift.drift_detected:
            drifted_clusters.append(cluster)

        if cluster.count == 1:
            esc = classify_singleton(cluster)
            cluster.singleton_label = esc.label
            cluster.singleton_escalated = esc.escalated
            cluster.singleton_reasoning = esc.reasoning
            cluster.singleton_score = esc.score
            if esc.escalated:
                singleton_escalations.append(cluster)

    if review_store is None:
        review_store = InMemoryReviewStore()
    reviewed_dispositions = _reviewed_dispositions_from_store(review_store)

    proposal = generate_recalibration_proposal(
        reviewed_dispositions=reviewed_dispositions,
        active_state=state,
    )
    if hasattr(review_store, "log_action"):
        review_store.log_action(
            "recalibration_proposal_created",
            "global",
            {
                "proposal_id": proposal.proposal_id,
                "current_similarity_threshold": proposal.current_similarity_threshold,
                "proposed_similarity_threshold": proposal.proposed_similarity_threshold,
                "current_window_hours": proposal.current_window_hours,
                "proposed_window_hours": proposal.proposed_window_hours,
                "status": proposal.status,
            },
        )

    return Iteration3Result(
        raw_alert_count=base.raw_alert_count,
        suppressed_alert_count=base.suppressed_alert_count,
        embedded_alert_count=base.embedded_alert_count,
        clusters=base.clusters,
        singletons=base.singletons,
        output_item_count=base.output_item_count,
        alert_reduction_ratio=base.alert_reduction_ratio,
        cluster_purity=base.cluster_purity,
        review_queue=build_review_queue(base.clusters),
        drifted_clusters=drifted_clusters,
        singleton_escalations=singleton_escalations,
        recalibration_proposals=[proposal],
        active_similarity_threshold=state.similarity_threshold,
        active_window_hours=state.window_hours,
    )


def run_iteration3_from_json(
    path: str,
    use_live_bedrock: bool = False,
    use_sqlite_suppression: bool = False,
    review_store=None,
    active_calibration_state: ActiveCalibrationState | None = None,
) -> Iteration3Result:
    state = active_calibration_state or _ACTIVE_CALIBRATION_STATE
    base = run_iteration2_from_json(
        path=path,
        use_live_bedrock=use_live_bedrock,
        use_sqlite_suppression=use_sqlite_suppression,
    )

    if review_store is None:
        review_store = InMemoryReviewStore()

    drifted_clusters = []
    singleton_escalations = []
    for cluster in base.clusters:
        drift = evaluate_cluster_drift(cluster)
        cluster.drift_detected = drift.drift_detected
        cluster.drift_score = drift.drift_score
        cluster.drift_reason = drift.reason
        cluster.drift_evidence = drift.evidence
        if drift.drift_detected:
            drifted_clusters.append(cluster)

        if cluster.count == 1:
            esc = classify_singleton(cluster)
            cluster.singleton_label = esc.label
            cluster.singleton_escalated = esc.escalated
            cluster.singleton_reasoning = esc.reasoning
            cluster.singleton_score = esc.score
            if esc.escalated:
                singleton_escalations.append(cluster)

    reviewed_dispositions = _reviewed_dispositions_from_store(review_store)
    proposal = generate_recalibration_proposal(
        reviewed_dispositions=reviewed_dispositions,
        active_state=state,
    )
    if hasattr(review_store, "log_action"):
        review_store.log_action(
            "recalibration_proposal_created",
            "global",
            {
                "proposal_id": proposal.proposal_id,
                "current_similarity_threshold": proposal.current_similarity_threshold,
                "proposed_similarity_threshold": proposal.proposed_similarity_threshold,
                "current_window_hours": proposal.current_window_hours,
                "proposed_window_hours": proposal.proposed_window_hours,
                "status": proposal.status,
            },
        )

    return Iteration3Result(
        raw_alert_count=base.raw_alert_count,
        suppressed_alert_count=base.suppressed_alert_count,
        embedded_alert_count=base.embedded_alert_count,
        clusters=base.clusters,
        singletons=base.singletons,
        output_item_count=base.output_item_count,
        alert_reduction_ratio=base.alert_reduction_ratio,
        cluster_purity=base.cluster_purity,
        review_queue=build_review_queue(base.clusters),
        drifted_clusters=drifted_clusters,
        singleton_escalations=singleton_escalations,
        recalibration_proposals=[proposal],
        active_similarity_threshold=state.similarity_threshold,
        active_window_hours=state.window_hours,
    )


def approve_recalibration_proposal(
    proposal: RecalibrationProposal,
    reviewed_by: str,
    reviewed_at: datetime,
    review_store=None,
    active_calibration_state: ActiveCalibrationState | None = None,
) -> RecalibrationProposal:
    state = active_calibration_state or _ACTIVE_CALIBRATION_STATE
    old_threshold = state.similarity_threshold
    old_window = state.window_hours
    approved = approve_proposal(
        proposal=proposal,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        active_state=state,
    )
    if review_store is not None and hasattr(review_store, "log_action"):
        review_store.log_action(
            "recalibration_approved",
            "global",
            {
                "proposal_id": proposal.proposal_id,
                "old_similarity_threshold": old_threshold,
                "new_similarity_threshold": state.similarity_threshold,
                "old_window_hours": old_window,
                "new_window_hours": state.window_hours,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at.isoformat(),
            },
        )
    return approved


def reject_recalibration_proposal(
    proposal: RecalibrationProposal,
    reviewed_by: str,
    reviewed_at: datetime,
    reason: str | None = None,
    review_store=None,
) -> RecalibrationProposal:
    rejected = reject_proposal(
        proposal=proposal,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        reason=reason,
    )
    if review_store is not None and hasattr(review_store, "log_action"):
        review_store.log_action(
            "recalibration_rejected",
            "global",
            {
                "proposal_id": proposal.proposal_id,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at.isoformat(),
                "reason": reason,
            },
        )
    return rejected
