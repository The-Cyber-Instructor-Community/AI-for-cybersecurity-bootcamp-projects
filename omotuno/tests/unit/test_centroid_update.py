from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.logic.centroid import update_centroid_incremental
from src.logic.clustering import assign_embedded_alert
from src.pipeline.types import AlertRecord, ClusterState, EmbeddedAlert


def test_incremental_centroid_math_exact_formula() -> None:
    c1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    c2 = update_centroid_incremental(c1, v2, new_count=2, renormalize=False)
    assert c2 == [0.5, 0.5]

    v3 = [1.0, 1.0]
    c3 = update_centroid_incremental(c2, v3, new_count=3, renormalize=False)
    assert abs(c3[0] - (2.0 / 3.0)) < 1e-9
    assert abs(c3[1] - (2.0 / 3.0)) < 1e-9


def test_incremental_centroid_with_optional_renormalization() -> None:
    c1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    c2 = update_centroid_incremental(c1, v2, new_count=2, renormalize=True)
    norm = (c2[0] ** 2 + c2[1] ** 2) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_chaining_drift_known_limitation_documented_by_behavior() -> None:
    now = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    cluster = ClusterState(
        cluster_id="c1",
        count=1,
        centroid=[1.0, 0.0],
        first_seen=now,
        last_seen=now,
        members=[],
        distinct_srcips=set(),
        distinct_users=set(),
        distinct_rule_ids=set(),
    )
    clusters = [cluster]

    def mk_alert(i: int) -> AlertRecord:
        ts = now + timedelta(minutes=i)
        return AlertRecord(
            alert_id=f"a{i}",
            timestamp=ts,
            rule_id="5710",
            rule_description="sshd authentication failed",
            full_log=f"log-{i}",
            srcip="10.0.0.1",
            srcuser="root",
            ground_truth_incident_id=f"inc-{i}",
        )

    # Gradual shift keeps each step close to current centroid.
    vectors = [[0.9, 0.1], [0.7, 0.3], [0.5, 0.5], [0.3, 0.7]]
    for i, vec in enumerate(vectors, start=1):
        embedded = EmbeddedAlert(alert=mk_alert(i), text="x", vector=vec)
        assign_embedded_alert(
            embedded,
            clusters,
            threshold=0.6,
            window=timedelta(hours=1),
            similarity_spy=None,
            renormalize_centroid=False,
        )

    assert len(clusters) == 1  # known Iteration 1 limitation: chaining can happen
