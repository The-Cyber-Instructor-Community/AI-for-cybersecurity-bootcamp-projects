from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import math

from src.logic.centroid import update_centroid_incremental
from src.logic.time_window import is_cluster_eligible
from src.pipeline.types import ClusterState, EmbeddedAlert, Vector


def cosine_similarity(a: Vector, b: Vector) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class SimilaritySpy:
    compared_cluster_ids: list[str] = field(default_factory=list)

    def record(self, cluster_id: str) -> None:
        self.compared_cluster_ids.append(cluster_id)


def create_new_cluster(cluster_id: str, embedded: EmbeddedAlert) -> ClusterState:
    alert = embedded.alert
    return ClusterState(
        cluster_id=cluster_id,
        count=1,
        centroid=embedded.vector[:],
        first_seen=alert.timestamp,
        last_seen=alert.timestamp,
        members=[alert],
        distinct_srcips={alert.srcip},
        distinct_users={alert.srcuser},
        distinct_rule_ids={alert.rule_id},
    )


def assign_embedded_alert(
    embedded: EmbeddedAlert,
    clusters: list[ClusterState],
    threshold: float,
    window: timedelta,
    similarity_spy: SimilaritySpy | None = None,
    renormalize_centroid: bool = False,
) -> ClusterState:
    """
    ADR-003 ordering: pre-filter eligibility before cosine scoring.
    ADR-002 assignment rule: join best eligible cluster if >= threshold else singleton.
    """
    eligible: list[ClusterState] = [
        cluster
        for cluster in clusters
        if not cluster.is_closed and is_cluster_eligible(embedded.alert.timestamp, cluster.last_seen, window)
    ]

    best_cluster: ClusterState | None = None
    best_score = -1.0
    for cluster in eligible:
        if similarity_spy is not None:
            similarity_spy.record(cluster.cluster_id)
        score = cosine_similarity(embedded.vector, cluster.centroid)
        if score > best_score:
            best_score = score
            best_cluster = cluster

    if best_cluster is not None and best_score >= threshold:
        best_cluster.count += 1
        best_cluster.centroid = update_centroid_incremental(
            best_cluster.centroid,
            embedded.vector,
            best_cluster.count,
            renormalize=renormalize_centroid,
        )
        best_cluster.last_seen = embedded.alert.timestamp
        best_cluster.members.append(embedded.alert)
        best_cluster.distinct_srcips.add(embedded.alert.srcip)
        best_cluster.distinct_users.add(embedded.alert.srcuser)
        best_cluster.distinct_rule_ids.add(embedded.alert.rule_id)

        # ADR-005 stale behavior used in Iteration 2:
        if best_cluster.summary is not None:
            best_cluster.summary_stale = True
            best_cluster.summary_status = "needs_review"

        return best_cluster

    cluster = create_new_cluster(f"cluster-{len(clusters) + 1}", embedded)
    clusters.append(cluster)
    return cluster
