from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.embed_agent import DeterministicEmbeddingClient
from src.logic.review_gate import (
    confirm_cluster,
    dismiss_cluster,
    escalate_cluster,
    merge_clusters,
    split_cluster,
)
from src.pipeline.types import AlertRecord, ClusterState
from src.store.review_store import InMemoryReviewStore
from src.store.suppression_store import InMemorySuppressionStore


def _mk_cluster(cluster_id: str, count: int, centroid: list[float], srcip: str = "10.0.0.1", rule_id: str = "5710") -> ClusterState:
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    members = []
    for i in range(count):
        members.append(
            AlertRecord(
                alert_id=f"{cluster_id}-a{i}",
                timestamp=now + timedelta(minutes=i),
                rule_id=rule_id,
                rule_description="sshd authentication failed",
                full_log=f"sshd: Failed password for root from {srcip} port {2200+i}",
                srcip=srcip,
                srcuser="root",
                ground_truth_incident_id="inc",
            )
        )
    return ClusterState(
        cluster_id=cluster_id,
        count=count,
        centroid=centroid,
        first_seen=members[0].timestamp,
        last_seen=members[-1].timestamp,
        members=members,
        distinct_srcips={srcip},
        distinct_users={"root"},
        distinct_rule_ids={rule_id},
    )


def test_confirm_writes_metadata_only() -> None:
    cluster = _mk_cluster("c1", 2, [1.0] * 8)
    store = InMemoryReviewStore()
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    pre_members = [m.alert_id for m in cluster.members]

    confirm_cluster(cluster, reviewed_by="analyst@example.com", reviewed_at=now, review_store=store)

    assert cluster.disposition == "confirmed"
    assert cluster.reviewed_by == "analyst@example.com"
    assert cluster.reviewed_at == now.isoformat()
    assert [m.alert_id for m in cluster.members] == pre_members
    assert len(store.entries) == 1
    assert store.entries[0].action == "confirm"


def test_dismiss_with_optional_suppression_and_expiry_required() -> None:
    cluster = _mk_cluster("c2", 3, [1.0] * 8)
    store = InMemoryReviewStore()
    suppression_store = InMemorySuppressionStore()
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="suppression expiry"):
        dismiss_cluster(
            cluster=cluster,
            reviewed_by="analyst@example.com",
            reviewed_at=now,
            review_store=store,
            suppression_store=suppression_store,
            create_suppression=True,
            suppression_expires_at=None,
        )
    assert cluster.disposition is None
    assert cluster.reviewed_by is None
    assert cluster.reviewed_at is None
    assert len(store.entries) == 0

    created = dismiss_cluster(
        cluster=cluster,
        reviewed_by="analyst@example.com",
        reviewed_at=now,
        review_store=store,
        suppression_store=suppression_store,
        create_suppression=True,
        suppression_expires_at=now + timedelta(hours=1),
    )
    assert cluster.disposition == "dismissed"
    assert created is not None
    assert suppression_store.get_rule("5710", "10.0.0.1") is not None


def test_escalate_requires_reference() -> None:
    cluster = _mk_cluster("c3", 1, [1.0] * 8)
    store = InMemoryReviewStore()
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="escalation_ref"):
        escalate_cluster(cluster, "analyst@example.com", now, "", store)

    escalate_cluster(cluster, "analyst@example.com", now, "TICKET-123", store)
    assert cluster.disposition == "escalated"
    assert cluster.escalation_ref == "TICKET-123"


def test_split_validates_and_recomputes() -> None:
    cluster = _mk_cluster("c4", 4, [1.0] * 8)
    store = InMemoryReviewStore()
    embed_client = DeterministicEmbeddingClient()
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="at least two"):
        split_cluster(cluster, [ [cluster.members[0].alert_id] ], "analyst@example.com", now, embed_client, store)

    groups = [
        [cluster.members[0].alert_id, cluster.members[1].alert_id],
        [cluster.members[2].alert_id, cluster.members[3].alert_id],
    ]
    new_clusters = split_cluster(cluster, groups, "analyst@example.com", now, embed_client, store)
    assert len(new_clusters) == 2
    assert cluster.disposition == "split"
    assert cluster.superseded_reason == "split"
    assert all(nc.count == 2 for nc in new_clusters)


def test_merge_weighted_centroid_and_invalid_self_merge() -> None:
    c1 = _mk_cluster("c5a", 2, [1.0, 0.0] + [0.0] * 6, srcip="10.0.0.1")
    c2 = _mk_cluster("c5b", 3, [0.0, 1.0] + [0.0] * 6, srcip="10.0.0.2")
    store = InMemoryReviewStore()
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="cannot merge"):
        merge_clusters(c1, c1, "analyst@example.com", now, store)

    merged = merge_clusters(c1, c2, "analyst@example.com", now, store)
    assert merged.count == 5
    assert abs(merged.centroid[0] - (2.0 / 5.0)) < 1e-9
    assert abs(merged.centroid[1] - (3.0 / 5.0)) < 1e-9
    assert c1.superseded_by == merged.cluster_id
    assert c2.superseded_by == merged.cluster_id
