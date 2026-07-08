from __future__ import annotations

from src.agents.embed_agent import DeterministicEmbeddingClient
from src.agents.summary_agent import DeterministicSummaryClient
from src.pipeline.ingest import load_alerts_from_records
from src.pipeline.run_iteration1 import run_iteration1
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.ui.dashboard import build_dashboard_view_model


def test_dashboard_before_after_counts_match_backend() -> None:
    alerts = load_alerts_from_records(generate_synthetic_wazuh_ssh_alerts(), require_synthetic=True)
    result = run_iteration1(
        alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=DeterministicSummaryClient(),
    )
    model = build_dashboard_view_model(result)

    assert model["before_count"] == 200
    assert model["after_count"] == result.output_item_count
    assert model["reduction_ratio"] == result.alert_reduction_ratio


def test_dashboard_cluster_details_fields() -> None:
    alerts = load_alerts_from_records(generate_synthetic_wazuh_ssh_alerts(), require_synthetic=True)
    result = run_iteration1(
        alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=DeterministicSummaryClient(),
    )
    model = build_dashboard_view_model(result)

    for row in model["cluster_rows"]:
        assert "count" in row
        assert "first_seen" in row
        assert "last_seen" in row
        assert "time_span_seconds" in row
        assert "source_ip" in row
        assert "summary" in row
        assert isinstance(row["summary"], str)
        assert row["summary"]
