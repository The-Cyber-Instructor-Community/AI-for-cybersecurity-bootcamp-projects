from __future__ import annotations

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
from src.logic.backstop import backstop_check_summary
from src.logic.cluster_close import close_eligible_clusters
from src.logic.clustering import SimilaritySpy, assign_embedded_alert
from src.logic.review_gate import build_review_queue
from src.logic.suppression import SuppressionEngine
from src.pipeline.config import SIMILARITY_THRESHOLD, SUPPRESSION_DB_PATH, WINDOW
from src.pipeline.ingest import load_alerts_from_json, load_alerts_from_records
from src.pipeline.run_iteration1 import _ensure_evaluable_synthetic, compute_cluster_purity
from src.pipeline.types import AlertRecord, ClusterState, Iteration2Result
from src.store.suppression_store import InMemorySuppressionStore, SQLiteSuppressionStore


def _volume_by_key(alerts: Iterable[AlertRecord]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for alert in alerts:
        key = (alert.rule_id, alert.srcip)
        counts[key] = counts.get(key, 0) + 1
    return counts


def run_iteration2(
    alerts: list[AlertRecord],
    embedding_client: EmbeddingClient,
    summary_client: SummaryClient,
    suppression_engine: SuppressionEngine,
    threshold: float = SIMILARITY_THRESHOLD,
    window: timedelta = WINDOW,
    renormalize_centroid: bool = False,
    similarity_spy: SimilaritySpy | None = None,
) -> Iteration2Result:
    _ensure_evaluable_synthetic(alerts)
    clusters: list[ClusterState] = []
    suppressed_count = 0
    embedded_count = 0
    volume_counts = _volume_by_key(alerts)

    for alert in alerts:
        decision = suppression_engine.decide(
            alert=alert,
            observed_volume=volume_counts.get((alert.rule_id, alert.srcip), 1),
            now=alert.timestamp,
        )
        if decision.suppressed:
            suppressed_count += 1
            continue

        embedded = embed_alert(alert, embedding_client)
        embedded_count += 1
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
            backstop_checker=backstop_check_summary,
        )

    if alerts:
        close_eligible_clusters(
            clusters=clusters,
            t_now=alerts[-1].timestamp,
            window=window,
            summary_builder=summary_client.summarize,
            force_close_all=True,
            backstop_checker=backstop_check_summary,
        )

    singletons = [c for c in clusters if c.count == 1]
    output_item_count = len(clusters)
    reduction = (len(alerts) / output_item_count) if output_item_count > 0 else 0.0
    purity = compute_cluster_purity(clusters)
    review_queue = build_review_queue(clusters)

    return Iteration2Result(
        raw_alert_count=len(alerts),
        suppressed_alert_count=suppressed_count,
        embedded_alert_count=embedded_count,
        clusters=clusters,
        singletons=singletons,
        output_item_count=output_item_count,
        alert_reduction_ratio=reduction,
        cluster_purity=purity,
        review_queue=review_queue,
    )


def run_iteration2_from_records(
    records: list[dict],
    use_live_bedrock: bool = False,
    use_sqlite_suppression: bool = False,
) -> Iteration2Result:
    alerts = load_alerts_from_records(records, require_synthetic=True)
    _ensure_evaluable_synthetic(alerts)

    if use_live_bedrock:
        embedding_client: EmbeddingClient = BedrockTitanEmbeddingClient()
        summary_client: SummaryClient = BedrockClaudeSummaryClient()
    else:
        embedding_client = DeterministicEmbeddingClient()
        summary_client = DeterministicSummaryClient()

    suppression_store = SQLiteSuppressionStore(SUPPRESSION_DB_PATH) if use_sqlite_suppression else InMemorySuppressionStore()
    suppression_engine = SuppressionEngine(suppression_store)
    return run_iteration2(
        alerts=alerts,
        embedding_client=embedding_client,
        summary_client=summary_client,
        suppression_engine=suppression_engine,
    )


def run_iteration2_from_json(
    path: str,
    use_live_bedrock: bool = False,
    use_sqlite_suppression: bool = False,
) -> Iteration2Result:
    alerts = load_alerts_from_json(path, require_synthetic=True)
    _ensure_evaluable_synthetic(alerts)

    if use_live_bedrock:
        embedding_client: EmbeddingClient = BedrockTitanEmbeddingClient()
        summary_client: SummaryClient = BedrockClaudeSummaryClient()
    else:
        embedding_client = DeterministicEmbeddingClient()
        summary_client = DeterministicSummaryClient()

    suppression_store = SQLiteSuppressionStore(SUPPRESSION_DB_PATH) if use_sqlite_suppression else InMemorySuppressionStore()
    suppression_engine = SuppressionEngine(suppression_store)
    return run_iteration2(
        alerts=alerts,
        embedding_client=embedding_client,
        summary_client=summary_client,
        suppression_engine=suppression_engine,
    )
