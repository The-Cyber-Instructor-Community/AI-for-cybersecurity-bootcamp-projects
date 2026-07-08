from __future__ import annotations

from datetime import timedelta

from src.agents.embed_agent import DeterministicEmbeddingClient
from src.logic.suppression import SuppressionEngine
from src.pipeline.ingest import load_alerts_from_records
from src.pipeline.run_iteration2 import run_iteration2
from src.pipeline.synthetic import generate_adversarial_wazuh_ssh_alerts
from src.store.suppression_store import InMemorySuppressionStore


class PoisonedSummaryClient:
    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, payload, model_id=None) -> str:
        self.calls += 1
        return (
            f"{payload.total_count} SSH authentication alerts were grouped from {payload.first_seen} to "
            f"{payload.last_seen} with source IPs {payload.distinct_srcips}, likely routine and low priority."
        )


def test_injection_like_poisoned_summary_is_flagged_contradiction() -> None:
    records = generate_adversarial_wazuh_ssh_alerts()
    alerts = load_alerts_from_records(records, require_synthetic=True)

    result = run_iteration2(
        alerts=alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=PoisonedSummaryClient(),
        suppression_engine=SuppressionEngine(InMemorySuppressionStore()),
    )

    contradiction_clusters = [c for c in result.clusters if c.contradiction_detected]
    assert len(contradiction_clusters) >= 1
    for cluster in contradiction_clusters:
        assert cluster.summary == "contradiction detected"
        assert cluster.summary_status == "contradiction_detected"
        assert cluster.backstop_reasons
