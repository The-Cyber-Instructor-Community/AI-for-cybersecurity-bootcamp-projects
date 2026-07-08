from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.embed_agent import DeterministicEmbeddingClient, embed_alert
from src.agents.summary_agent import DeterministicSummaryClient
from src.logic.clustering import assign_embedded_alert
from src.logic.review_gate import open_cluster_for_review
from src.pipeline.ingest import load_alerts_from_records
from src.pipeline.run_iteration2 import run_iteration2
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.store.suppression_store import InMemorySuppressionStore
from src.logic.suppression import SuppressionEngine


def test_stale_cache_regeneration_integration() -> None:
    alerts = load_alerts_from_records(generate_synthetic_wazuh_ssh_alerts(), require_synthetic=True)
    summary_client = DeterministicSummaryClient()
    result = run_iteration2(
        alerts=alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=summary_client,
        suppression_engine=SuppressionEngine(InMemorySuppressionStore()),
    )

    target = result.clusters[0]
    target.is_closed = False  # simulate active-cluster join path for ADR-005 stale behavior
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    open_cluster_for_review(target, summary_client=summary_client, reviewed_at=now)
    calls_after_open = len(summary_client.calls)

    new_alert = target.members[-1]
    joined_alert = type(new_alert)(
        **{
            **new_alert.__dict__,
            "alert_id": "late-join",
            "timestamp": new_alert.timestamp + timedelta(minutes=5),
            "full_log": new_alert.full_log + " retry",
        }
    )
    embedded = embed_alert(joined_alert, DeterministicEmbeddingClient())
    assign_embedded_alert(
        embedded=embedded,
        clusters=[target],
        threshold=-1.0,
        window=timedelta(hours=12),
    )
    assert target.summary_stale is True
    assert len(summary_client.calls) == calls_after_open

    open_cluster_for_review(target, summary_client=summary_client, reviewed_at=now + timedelta(minutes=1))
    assert target.summary_stale is False
    assert len(summary_client.calls) == calls_after_open + 1
