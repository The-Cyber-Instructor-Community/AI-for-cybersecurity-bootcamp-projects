from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


Vector = list[float]


@dataclass(frozen=True)
class AlertRecord:
    alert_id: str
    timestamp: datetime
    rule_id: str
    rule_description: str
    full_log: str
    srcip: str
    srcuser: str
    ground_truth_incident_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddedAlert:
    alert: AlertRecord
    text: str
    vector: Vector


@dataclass
class ClusterState:
    cluster_id: str
    count: int
    centroid: Vector
    first_seen: datetime
    last_seen: datetime
    members: list[AlertRecord] = field(default_factory=list)
    distinct_srcips: set[str] = field(default_factory=set)
    distinct_users: set[str] = field(default_factory=set)
    distinct_rule_ids: set[str] = field(default_factory=set)
    summary: str | None = None
    is_closed: bool = False

    # Iteration 2 state
    summary_stale: bool = False
    summary_generated_at: str | None = None
    summary_status: str = "ok"  # ok | contradiction_detected | needs_review
    contradiction_detected: bool = False
    backstop_reasons: list[str] = field(default_factory=list)

    disposition: str | None = None  # confirmed | dismissed | escalated | split | merged
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    escalation_ref: str | None = None

    superseded_by: str | None = None
    superseded_reason: str | None = None

    # Iteration 3 state
    drift_detected: bool = False
    drift_score: float = 0.0
    drift_reason: str | None = None
    drift_evidence: dict[str, Any] = field(default_factory=dict)

    singleton_label: str | None = None  # novel | routine
    singleton_escalated: bool = False
    singleton_reasoning: str | None = None
    singleton_score: float = 0.0

    def time_span(self) -> timedelta:
        return self.last_seen - self.first_seen


@dataclass(frozen=True)
class SummaryInput:
    total_count: int
    first_seen: str
    last_seen: str
    distinct_srcips: str
    distinct_usernames: str
    distinct_rule_ids: int
    sample_first_log: str
    sample_last_log: str
    sample_outlier_log: str


@dataclass(frozen=True)
class Iteration1Result:
    raw_alert_count: int
    clusters: list[ClusterState]
    singletons: list[ClusterState]
    output_item_count: int
    alert_reduction_ratio: float
    cluster_purity: float


@dataclass(frozen=True)
class Iteration2Result:
    raw_alert_count: int
    suppressed_alert_count: int
    embedded_alert_count: int
    clusters: list[ClusterState]
    singletons: list[ClusterState]
    output_item_count: int
    alert_reduction_ratio: float
    cluster_purity: float
    review_queue: list[ClusterState]


@dataclass(frozen=True)
class RecalibrationProposal:
    proposal_id: str
    current_similarity_threshold: float
    proposed_similarity_threshold: float
    current_window_hours: int
    proposed_window_hours: int
    split_count: int
    merge_count: int
    rationale: str
    risk_notes: str
    clamped: bool = False
    status: str = "pending_approval"  # pending_approval | approved | rejected
    created_at: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class Iteration3Result:
    raw_alert_count: int
    suppressed_alert_count: int
    embedded_alert_count: int
    clusters: list[ClusterState]
    singletons: list[ClusterState]
    output_item_count: int
    alert_reduction_ratio: float
    cluster_purity: float
    review_queue: list[ClusterState]
    drifted_clusters: list[ClusterState]
    singleton_escalations: list[ClusterState]
    recalibration_proposals: list[RecalibrationProposal]
    active_similarity_threshold: float
    active_window_hours: int
