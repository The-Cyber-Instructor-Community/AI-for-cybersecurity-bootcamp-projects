from __future__ import annotations

from datetime import datetime
from typing import Iterable

from src.agents.embed_agent import EmbeddingClient, embed_alert
from src.logic.backstop import backstop_check_summary
from src.logic.cluster_close import regenerate_summary_if_stale_or_missing
from src.pipeline.types import AlertRecord, ClusterState
from src.store.suppression_store import SuppressionRule


def get_action_descriptors() -> list[dict]:
    return [
        {"action": "confirm", "required_fields": ["reviewed_by"]},
        {"action": "dismiss", "required_fields": ["reviewed_by"], "optional_fields": ["create_suppression", "expires_at"]},
        {"action": "split", "required_fields": ["reviewed_by", "partitions"]},
        {"action": "merge", "required_fields": ["reviewed_by", "cluster_ids"]},
        {"action": "escalate", "required_fields": ["reviewed_by", "escalation_ref"]},
    ]


def _ensure_actionable(cluster: ClusterState) -> None:
    if cluster.superseded_by is not None:
        raise ValueError("cluster is superseded and cannot be directly reviewed")


def _mark_reviewed(cluster: ClusterState, disposition: str, reviewed_by: str, reviewed_at: datetime) -> None:
    if not reviewed_by:
        raise ValueError("reviewed_by is required")
    cluster.disposition = disposition
    cluster.reviewed_by = reviewed_by
    cluster.reviewed_at = reviewed_at.isoformat()


def confirm_cluster(cluster: ClusterState, reviewed_by: str, reviewed_at: datetime, review_store) -> None:
    _ensure_actionable(cluster)
    _mark_reviewed(cluster, "confirmed", reviewed_by, reviewed_at)
    review_store.log_action(
        "confirm",
        cluster.cluster_id,
        {"reviewed_by": reviewed_by, "reviewed_at": cluster.reviewed_at},
    )


def dismiss_cluster(
    cluster: ClusterState,
    reviewed_by: str,
    reviewed_at: datetime,
    review_store,
    suppression_store=None,
    create_suppression: bool = False,
    suppression_expires_at: datetime | None = None,
) -> SuppressionRule | None:
    _ensure_actionable(cluster)

    created_rule: SuppressionRule | None = None
    if create_suppression:
        if suppression_expires_at is None:
            raise ValueError("suppression expiry is required when create_suppression=True")
        if len(cluster.distinct_rule_ids) != 1 or len(cluster.distinct_srcips) != 1:
            raise ValueError("suppression creation requires a single rule_id and single srcip cluster")
        if suppression_store is None:
            raise ValueError("suppression_store is required for suppression creation")
        created_rule = SuppressionRule(
            rule_id=next(iter(cluster.distinct_rule_ids)),
            srcip=next(iter(cluster.distinct_srcips)),
            expires_at=suppression_expires_at,
            baseline_volume=cluster.count,
        )
        suppression_store.upsert_rule(created_rule)

    _mark_reviewed(cluster, "dismissed", reviewed_by, reviewed_at)
    review_store.log_action(
        "dismiss",
        cluster.cluster_id,
        {
            "reviewed_by": reviewed_by,
            "reviewed_at": cluster.reviewed_at,
            "create_suppression": create_suppression,
            "suppression_expires_at": suppression_expires_at.isoformat() if suppression_expires_at else None,
        },
    )
    return created_rule


def escalate_cluster(
    cluster: ClusterState,
    reviewed_by: str,
    reviewed_at: datetime,
    escalation_ref: str,
    review_store,
) -> None:
    _ensure_actionable(cluster)
    if not escalation_ref:
        raise ValueError("escalation_ref is required")
    _mark_reviewed(cluster, "escalated", reviewed_by, reviewed_at)
    cluster.escalation_ref = escalation_ref
    review_store.log_action(
        "escalate",
        cluster.cluster_id,
        {
            "reviewed_by": reviewed_by,
            "reviewed_at": cluster.reviewed_at,
            "escalation_ref": escalation_ref,
        },
    )


def split_cluster(
    cluster: ClusterState,
    partitions: list[list[str]],
    reviewed_by: str,
    reviewed_at: datetime,
    embedding_client: EmbeddingClient,
    review_store,
) -> list[ClusterState]:
    _ensure_actionable(cluster)
    if len(partitions) < 2:
        raise ValueError("split requires at least two partitions")

    by_id: dict[str, AlertRecord] = {m.alert_id: m for m in cluster.members}
    seen: set[str] = set()

    for group in partitions:
        if not group:
            raise ValueError("split partitions cannot be empty")
        for aid in group:
            if aid not in by_id:
                raise ValueError(f"unknown alert_id in split partition: {aid}")
            if aid in seen:
                raise ValueError(f"duplicate alert_id across split partitions: {aid}")
            seen.add(aid)

    if seen != set(by_id.keys()):
        raise ValueError("split partitions must cover all original members exactly once")

    new_clusters: list[ClusterState] = []
    for idx, group in enumerate(partitions, start=1):
        members = [by_id[aid] for aid in group]
        embedded = [embed_alert(alert, embedding_client) for alert in members]
        count = len(embedded)
        centroid = [0.0] * len(embedded[0].vector)
        for emb in embedded:
            centroid = [c + v for c, v in zip(centroid, emb.vector)]
        centroid = [c / count for c in centroid]

        new_cluster = ClusterState(
            cluster_id=f"{cluster.cluster_id}-split-{idx}",
            count=count,
            centroid=centroid,
            first_seen=min(m.timestamp for m in members),
            last_seen=max(m.timestamp for m in members),
            members=members,
            distinct_srcips={m.srcip for m in members},
            distinct_users={m.srcuser for m in members},
            distinct_rule_ids={m.rule_id for m in members},
        )
        new_clusters.append(new_cluster)

    _mark_reviewed(cluster, "split", reviewed_by, reviewed_at)
    cluster.superseded_by = ",".join(c.cluster_id for c in new_clusters)
    cluster.superseded_reason = "split"

    review_store.log_action(
        "split",
        cluster.cluster_id,
        {
            "reviewed_by": reviewed_by,
            "reviewed_at": cluster.reviewed_at,
            "new_cluster_ids": [c.cluster_id for c in new_clusters],
        },
    )

    return new_clusters


def merge_clusters(
    cluster_a: ClusterState,
    cluster_b: ClusterState,
    reviewed_by: str,
    reviewed_at: datetime,
    review_store,
) -> ClusterState:
    _ensure_actionable(cluster_a)
    _ensure_actionable(cluster_b)
    if cluster_a.cluster_id == cluster_b.cluster_id:
        raise ValueError("cannot merge a cluster with itself")

    n1, n2 = cluster_a.count, cluster_b.count
    merged_count = n1 + n2
    merged_centroid = [((n1 * c1) + (n2 * c2)) / merged_count for c1, c2 in zip(cluster_a.centroid, cluster_b.centroid)]

    members_map: dict[str, AlertRecord] = {m.alert_id: m for m in cluster_a.members}
    for m in cluster_b.members:
        members_map[m.alert_id] = m
    merged_members = list(members_map.values())

    merged = ClusterState(
        cluster_id=f"{cluster_a.cluster_id}-merge-{cluster_b.cluster_id}",
        count=merged_count,
        centroid=merged_centroid,
        first_seen=min(cluster_a.first_seen, cluster_b.first_seen),
        last_seen=max(cluster_a.last_seen, cluster_b.last_seen),
        members=merged_members,
        distinct_srcips=cluster_a.distinct_srcips | cluster_b.distinct_srcips,
        distinct_users=cluster_a.distinct_users | cluster_b.distinct_users,
        distinct_rule_ids=cluster_a.distinct_rule_ids | cluster_b.distinct_rule_ids,
    )

    _mark_reviewed(cluster_a, "merged", reviewed_by, reviewed_at)
    _mark_reviewed(cluster_b, "merged", reviewed_by, reviewed_at)
    cluster_a.superseded_by = merged.cluster_id
    cluster_b.superseded_by = merged.cluster_id
    cluster_a.superseded_reason = "merge"
    cluster_b.superseded_reason = "merge"

    review_store.log_action(
        "merge",
        merged.cluster_id,
        {
            "reviewed_by": reviewed_by,
            "reviewed_at": reviewed_at.isoformat(),
            "input_cluster_ids": [cluster_a.cluster_id, cluster_b.cluster_id],
        },
    )
    return merged


def open_cluster_for_review(cluster: ClusterState, summary_client, reviewed_at: datetime) -> bool:
    changed = regenerate_summary_if_stale_or_missing(
        cluster=cluster,
        summary_builder=summary_client.summarize,
        backstop_checker=backstop_check_summary,
        generated_at=reviewed_at,
    )
    return changed


def build_review_queue(clusters: Iterable[ClusterState]) -> list[ClusterState]:
    return [
        c
        for c in clusters
        if c.superseded_by is None and (c.disposition is None or c.contradiction_detected)
    ]
