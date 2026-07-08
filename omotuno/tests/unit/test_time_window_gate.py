from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.logic.clustering import SimilaritySpy, assign_embedded_alert
from src.logic.time_window import is_cluster_eligible
from src.pipeline.types import AlertRecord, ClusterState, EmbeddedAlert


def _alert(ts: datetime, aid: str, srcip: str, srcuser: str, gt: str) -> AlertRecord:
    return AlertRecord(
        alert_id=aid,
        timestamp=ts,
        rule_id="5710",
        rule_description="sshd authentication failed",
        full_log=f"sshd: Failed password for {srcuser} from {srcip}",
        srcip=srcip,
        srcuser=srcuser,
        ground_truth_incident_id=gt,
    )


def test_time_window_prefilter_runs_before_similarity() -> None:
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    window = timedelta(hours=1)

    expired_cluster = ClusterState(
        cluster_id="c-expired",
        count=2,
        centroid=[1.0, 0.0],
        first_seen=now - timedelta(hours=3),
        last_seen=now - timedelta(hours=2),
        members=[_alert(now - timedelta(hours=3), "e1", "10.0.0.10", "root", "inc-a")],
        distinct_srcips={"10.0.0.10"},
        distinct_users={"root"},
        distinct_rule_ids={"5710"},
    )
    eligible_cluster = ClusterState(
        cluster_id="c-eligible",
        count=2,
        centroid=[0.8, 0.6],
        first_seen=now - timedelta(minutes=30),
        last_seen=now - timedelta(minutes=10),
        members=[_alert(now - timedelta(minutes=30), "b1", "10.0.0.20", "admin", "inc-b")],
        distinct_srcips={"10.0.0.20"},
        distinct_users={"admin"},
        distinct_rule_ids={"5710"},
    )
    clusters = [expired_cluster, eligible_cluster]

    incoming = EmbeddedAlert(
        alert=_alert(now, "n1", "10.0.0.99", "svc", "inc-b"),
        text="x",
        vector=[1.0, 0.0],
    )
    spy = SimilaritySpy()
    assigned = assign_embedded_alert(
        incoming,
        clusters,
        threshold=0.7,
        window=window,
        similarity_spy=spy,
    )

    assert assigned.cluster_id == "c-eligible"
    assert spy.compared_cluster_ids == ["c-eligible"]
    assert eligible_cluster.last_seen == now


def test_time_window_boundary_conditions() -> None:
    now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    window = timedelta(hours=1)
    assert is_cluster_eligible(now, now - timedelta(hours=1), window) is True
    assert is_cluster_eligible(now, now - timedelta(hours=1, seconds=1), window) is False
