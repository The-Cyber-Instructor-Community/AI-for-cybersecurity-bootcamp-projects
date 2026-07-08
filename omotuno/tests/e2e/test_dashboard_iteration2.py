from __future__ import annotations

from src.agents.embed_agent import DeterministicEmbeddingClient
from src.agents.summary_agent import DeterministicSummaryClient
from datetime import datetime, timezone

from src.logic.review_gate import split_cluster
from src.logic.suppression import SuppressionEngine
from src.pipeline.ingest import load_alerts_from_records
from src.pipeline.run_iteration2 import run_iteration2
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.store.review_store import InMemoryReviewStore
from src.store.suppression_store import InMemorySuppressionStore
from src.ui.dashboard import build_dashboard_view_model


def test_dashboard_iteration2_review_queue_and_states() -> None:
    alerts = load_alerts_from_records(generate_synthetic_wazuh_ssh_alerts(), require_synthetic=True)
    result = run_iteration2(
        alerts=alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=DeterministicSummaryClient(),
        suppression_engine=SuppressionEngine(InMemorySuppressionStore()),
    )
    model = build_dashboard_view_model(result)

    assert "review_queue" in model
    assert "unreviewed_count" in model
    assert model["unreviewed_count"] == len(model["review_queue"])
    assert "suppressed_alert_count" in model
    assert "embedded_alert_count" in model

    first_row = model["cluster_rows"][0]
    assert "contradiction_detected" in first_row
    assert "backstop_reasons" in first_row
    assert "summary_stale" in first_row
    assert "summary_status" in first_row
    assert "disposition" in first_row
    assert "superseded_by" in first_row
    assert "raw_facts" in first_row
    assert "action_descriptors" in first_row

    actions = {a["action"] for a in first_row["action_descriptors"]}
    assert actions == {"confirm", "dismiss", "split", "merge", "escalate"}


def test_dashboard_review_queue_excludes_superseded_clusters() -> None:
    alerts = load_alerts_from_records(generate_synthetic_wazuh_ssh_alerts(), require_synthetic=True)
    result = run_iteration2(
        alerts=alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=DeterministicSummaryClient(),
        suppression_engine=SuppressionEngine(InMemorySuppressionStore()),
    )
    target = next(c for c in result.clusters if c.count >= 2)
    midpoint = len(target.members) // 2
    partitions = [
        [m.alert_id for m in target.members[:midpoint]],
        [m.alert_id for m in target.members[midpoint:]],
    ]
    split_cluster(
        cluster=target,
        partitions=partitions,
        reviewed_by="analyst@example.com",
        reviewed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        embedding_client=DeterministicEmbeddingClient(),
        review_store=InMemoryReviewStore(),
    )

    model = build_dashboard_view_model(result)
    queued_ids = {row["cluster_id"] for row in model["review_queue"]}
    assert target.cluster_id not in queued_ids
