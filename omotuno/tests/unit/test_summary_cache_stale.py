from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.embed_agent import DeterministicEmbeddingClient, embed_alert
from src.agents.summary_agent import DeterministicSummaryClient
from src.logic.clustering import assign_embedded_alert
from src.logic.review_gate import open_cluster_for_review
from src.pipeline.types import AlertRecord, ClusterState


def _make_cluster_with_two_members(now: datetime) -> ClusterState:
    m1 = AlertRecord(
        alert_id="a1",
        timestamp=now,
        rule_id="5710",
        rule_description="sshd authentication failed",
        full_log="sshd: Failed password for root from 10.0.0.1",
        srcip="10.0.0.1",
        srcuser="root",
        ground_truth_incident_id="inc-1",
    )
    m2 = AlertRecord(
        alert_id="a2",
        timestamp=now + timedelta(minutes=1),
        rule_id="5710",
        rule_description="sshd authentication failed",
        full_log="sshd: Failed password for root from 10.0.0.1 port 23",
        srcip="10.0.0.1",
        srcuser="root",
        ground_truth_incident_id="inc-1",
    )
    return ClusterState(
        cluster_id="c1",
        count=2,
        centroid=[1.0] * 8,
        first_seen=m1.timestamp,
        last_seen=m2.timestamp,
        members=[m1, m2],
        distinct_srcips={"10.0.0.1"},
        distinct_users={"root"},
        distinct_rule_ids={"5710"},
    )


def test_stale_flag_lifecycle_and_regeneration() -> None:
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    cluster = _make_cluster_with_two_members(now)
    summary_client = DeterministicSummaryClient()
    embed_client = DeterministicEmbeddingClient()

    changed = open_cluster_for_review(cluster, summary_client=summary_client, reviewed_at=now)
    assert changed is True
    assert cluster.summary is not None
    assert cluster.summary_stale is False
    initial_calls = len(summary_client.calls)

    new_alert = AlertRecord(
        alert_id="a3",
        timestamp=now + timedelta(minutes=2),
        rule_id="5710",
        rule_description="sshd authentication failed",
        full_log="sshd: Failed password for root from 10.0.0.1 port 24",
        srcip="10.0.0.1",
        srcuser="root",
        ground_truth_incident_id="inc-1",
    )
    embedded = embed_alert(new_alert, embed_client)
    assign_embedded_alert(
        embedded=embedded,
        clusters=[cluster],
        threshold=-1.0,
        window=timedelta(hours=1),
    )
    assert cluster.summary_stale is True
    assert len(summary_client.calls) == initial_calls

    changed_again = open_cluster_for_review(cluster, summary_client=summary_client, reviewed_at=now + timedelta(minutes=3))
    assert changed_again is True
    assert cluster.summary_stale is False
    assert len(summary_client.calls) == initial_calls + 1

    changed_third = open_cluster_for_review(cluster, summary_client=summary_client, reviewed_at=now + timedelta(minutes=4))
    assert changed_third is False
    assert len(summary_client.calls) == initial_calls + 1
