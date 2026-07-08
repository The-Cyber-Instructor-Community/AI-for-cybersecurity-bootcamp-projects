from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.logic.drift_agent import evaluate_cluster_drift
from src.pipeline.types import AlertRecord, ClusterState


def _cluster_from_logs(logs: list[str], superseded: bool = False) -> ClusterState:
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    members = [
        AlertRecord(
            alert_id=f"a{i}",
            timestamp=base + timedelta(minutes=i),
            rule_id="5710",
            rule_description="sshd authentication failed",
            full_log=log,
            srcip="10.0.0.10",
            srcuser="root",
            ground_truth_incident_id="inc",
        )
        for i, log in enumerate(logs)
    ]
    c = ClusterState(
        cluster_id="c1",
        count=len(members),
        centroid=[0.1] * 8,
        first_seen=members[0].timestamp,
        last_seen=members[-1].timestamp,
        members=members,
        distinct_srcips={m.srcip for m in members},
        distinct_users={m.srcuser for m in members},
        distinct_rule_ids={m.rule_id for m in members},
    )
    if superseded:
        c.superseded_by = "c2"
    return c


def test_drift_minimum_evidence_and_not_active() -> None:
    c_small = _cluster_from_logs(
        [
            "sshd: Failed password for root from 10.0.0.10 port 2200 ssh2",
            "sshd: Failed password for root from 10.0.0.10 port 2201 ssh2",
        ]
    )
    r_small = evaluate_cluster_drift(c_small)
    assert r_small.drift_detected is False
    assert r_small.reason == "insufficient_evidence"

    c_sup = _cluster_from_logs(
        [
            "sshd: Failed password for root from 10.0.0.10 port 2200 ssh2",
            "sshd: Failed password for root from 10.0.0.10 port 2201 ssh2",
            "sshd: Failed password for root from 10.0.0.10 port 2202 ssh2",
            "sshd: Failed password for root from 10.0.0.10 port 2203 ssh2",
        ],
        superseded=True,
    )
    r_sup = evaluate_cluster_drift(c_sup)
    assert r_sup.drift_detected is False
    assert r_sup.reason == "not_active"


def test_drift_false_positive_control_on_coherent_cluster() -> None:
    coherent_logs = [
        f"sshd: Failed password for root from 10.0.0.10 port {2200+i} ssh2"
        for i in range(12)
    ]
    coherent = _cluster_from_logs(coherent_logs)
    result = evaluate_cluster_drift(coherent)
    assert result.drift_detected is False
    assert result.reason == "within_threshold"


def test_drift_true_positive_control_on_drift_injected_cluster() -> None:
    coherent_prefix = [
        f"sshd: Failed password for root from 10.0.0.10 port {2200+i} ssh2"
        for i in range(6)
    ]
    drift_tail = [
        "sshd: Failed password for postgres from 10.0.0.10 port 3306 ssh2 sudo token exfiltration",
        "sshd: Invalid user oracle from 10.0.0.10 port 3307 ssh2 suspicious lateral movement",
        "sshd: Failed password for backup from 10.0.0.10 port 3308 ssh2 privilege escalation attempt",
        "sshd: Invalid user deploy from 10.0.0.10 port 3309 ssh2 unusual command sequence",
    ]
    drifted = _cluster_from_logs(coherent_prefix + drift_tail)
    result = evaluate_cluster_drift(drifted)
    assert result.drift_detected is True
    assert result.reason == "centroid_drift"


def test_drift_threshold_boundary_behavior() -> None:
    coherent_prefix = [
        f"sshd: Failed password for root from 10.0.0.10 port {2200+i} ssh2"
        for i in range(6)
    ]
    drift_tail = [
        "sshd: Invalid user oracle from 10.0.0.10 port 3307 ssh2 suspicious lateral movement",
        "sshd: Failed password for backup from 10.0.0.10 port 3308 ssh2 privilege escalation attempt",
        "sshd: Invalid user deploy from 10.0.0.10 port 3309 ssh2 unusual command sequence",
    ]
    c = _cluster_from_logs(coherent_prefix + drift_tail)
    baseline = evaluate_cluster_drift(c)
    r_equal = evaluate_cluster_drift(c, threshold=baseline.drift_score)
    r_above = evaluate_cluster_drift(c, threshold=baseline.drift_score + 0.01)
    r_below = evaluate_cluster_drift(c, threshold=baseline.drift_score - 0.01)

    assert r_equal.drift_detected is True  # contract: >= threshold flags
    assert r_above.drift_detected is False
    assert r_below.drift_detected is True
