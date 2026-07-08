from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from src.agents.embed_agent import (
    BedrockTitanEmbeddingClient,
    DeterministicEmbeddingClient,
    EmbeddingClient,
    embed_alert,
)
from src.agents.summary_agent import (
    BedrockClaudeSummaryClient,
    DeterministicSummaryClient,
    SummaryClient,
)
from src.logic.cluster_close import close_eligible_clusters
from src.logic.clustering import SimilaritySpy, assign_embedded_alert
from src.pipeline.config import SIMILARITY_THRESHOLD, VECTOR_STORE_BACKEND, WINDOW
from src.pipeline.ingest import load_alerts_from_json, load_alerts_from_records
from src.pipeline.types import AlertRecord, ClusterState, Iteration1Result
from src.store.cluster_store import create_cluster_store


@dataclass(frozen=True)
class EvalMetrics:
    cluster_purity: float
    alert_reduction_ratio: float


def compute_cluster_purity(clusters: Iterable[ClusterState]) -> float:
    members = [m for c in clusters for m in c.members]
    if not members:
        return 0.0

    labeled_total = 0
    weighted_sum = 0.0
    for cluster in clusters:
        gt_counts: dict[str, int] = {}
        cluster_labeled = 0
        for member in cluster.members:
            if member.ground_truth_incident_id is None:
                continue
            cluster_labeled += 1
            gt = member.ground_truth_incident_id
            gt_counts[gt] = gt_counts.get(gt, 0) + 1
        if cluster_labeled == 0:
            continue
        labeled_total += cluster_labeled
        weighted_sum += max(gt_counts.values()) if gt_counts else 0.0
    if labeled_total == 0:
        return 0.0
    return weighted_sum / labeled_total


def run_iteration1(
    alerts: list[AlertRecord],
    embedding_client: EmbeddingClient,
    summary_client: SummaryClient,
    threshold: float = SIMILARITY_THRESHOLD,
    window: timedelta = WINDOW,
    renormalize_centroid: bool = False,
    similarity_spy: SimilaritySpy | None = None,
    vector_store_backend: str = VECTOR_STORE_BACKEND,
) -> Iteration1Result:
    _ensure_evaluable_synthetic(alerts)
    cluster_store = create_cluster_store(vector_store_backend)
    clusters: list[ClusterState] = cluster_store.all()

    for alert in alerts:
        embedded = embed_alert(alert, embedding_client)
        assign_embedded_alert(
            embedded,
            clusters,
            threshold=threshold,
            window=window,
            similarity_spy=similarity_spy,
            renormalize_centroid=renormalize_centroid,
        )
        close_eligible_clusters(
            clusters=clusters,
            t_now=alert.timestamp,
            window=window,
            summary_builder=summary_client.summarize,
            force_close_all=False,
        )

    # End-of-batch finalization for demo output.
    if alerts:
        close_eligible_clusters(
            clusters=clusters,
            t_now=alerts[-1].timestamp,
            window=window,
            summary_builder=summary_client.summarize,
            force_close_all=True,
        )

    singletons = [c for c in clusters if c.count == 1]
    output_item_count = len(clusters)
    reduction = (len(alerts) / output_item_count) if output_item_count > 0 else 0.0
    purity = compute_cluster_purity(clusters)

    return Iteration1Result(
        raw_alert_count=len(alerts),
        clusters=clusters,
        singletons=singletons,
        output_item_count=output_item_count,
        alert_reduction_ratio=reduction,
        cluster_purity=purity,
    )


def _ensure_evaluable_synthetic(alerts: list[AlertRecord]) -> None:
    if any(a.ground_truth_incident_id is None for a in alerts):
        raise ValueError("synthetic evaluation requires ground_truth_incident_id on every alert")


def run_iteration1_from_records(
    records: list[dict],
    use_live_bedrock: bool = False,
    vector_store_backend: str = VECTOR_STORE_BACKEND,
) -> Iteration1Result:
    alerts = load_alerts_from_records(records, require_synthetic=True)
    _ensure_evaluable_synthetic(alerts)
    if use_live_bedrock:
        embedding_client: EmbeddingClient = BedrockTitanEmbeddingClient()
        summary_client: SummaryClient = BedrockClaudeSummaryClient()
    else:
        embedding_client = DeterministicEmbeddingClient()
        summary_client = DeterministicSummaryClient()
    return run_iteration1(
        alerts,
        embedding_client=embedding_client,
        summary_client=summary_client,
        vector_store_backend=vector_store_backend,
    )


def run_iteration1_from_json(
    path: str,
    use_live_bedrock: bool = False,
    vector_store_backend: str = VECTOR_STORE_BACKEND,
) -> Iteration1Result:
    alerts = load_alerts_from_json(path, require_synthetic=True)
    _ensure_evaluable_synthetic(alerts)
    if use_live_bedrock:
        embedding_client: EmbeddingClient = BedrockTitanEmbeddingClient()
        summary_client: SummaryClient = BedrockClaudeSummaryClient()
    else:
        embedding_client = DeterministicEmbeddingClient()
        summary_client = DeterministicSummaryClient()
    return run_iteration1(
        alerts,
        embedding_client=embedding_client,
        summary_client=summary_client,
        vector_store_backend=vector_store_backend,
    )
