from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.embed_agent import DeterministicEmbeddingClient
from src.agents.summary_agent import DeterministicSummaryClient, one_sentence_validator
from src.pipeline.ingest import load_alerts_from_records
import pytest

from src.pipeline.run_iteration1 import run_iteration1, run_iteration1_from_records
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts


def test_golden_pipeline_200_alerts() -> None:
    records = generate_synthetic_wazuh_ssh_alerts()
    alerts = load_alerts_from_records(records, require_synthetic=True)
    embed_client = DeterministicEmbeddingClient()
    summary_client = DeterministicSummaryClient()

    result = run_iteration1(alerts, embedding_client=embed_client, summary_client=summary_client)

    assert result.raw_alert_count == 200
    assert result.output_item_count >= 5
    assert result.alert_reduction_ratio > 1.0
    assert result.cluster_purity > 0.9
    assert len(summary_client.calls) == len(result.clusters)

    for cluster in result.clusters:
        assert cluster.count >= 1
        assert cluster.last_seen >= cluster.first_seen
        assert cluster.summary is not None
        assert one_sentence_validator(cluster.summary)
        assert len(cluster.distinct_srcips) >= 1


def test_time_window_false_merge_prevention() -> None:
    base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    records = [
        {
            "timestamp": (base + timedelta(minutes=0)).isoformat().replace("+00:00", "Z"),
            "rule": {"id": "5710", "description": "sshd authentication failed"},
            "full_log": "sshd: Failed password for root from 10.0.0.10 port 22 ssh2",
            "srcip": "10.0.0.10",
            "srcuser": "root",
            "event_type": "ssh_auth_failure",
            "ground_truth_incident_id": "inc-1",
            "synthetic": True,
        },
        {
            "timestamp": (base + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "rule": {"id": "5710", "description": "sshd authentication failed"},
            "full_log": "sshd: Failed password for root from 10.0.0.10 port 23 ssh2",
            "srcip": "10.0.0.10",
            "srcuser": "root",
            "event_type": "ssh_auth_failure",
            "ground_truth_incident_id": "inc-1",
            "synthetic": True,
        },
        {
            "timestamp": (base + timedelta(hours=13)).isoformat().replace("+00:00", "Z"),
            "rule": {"id": "5710", "description": "sshd authentication failed"},
            "full_log": "sshd: Failed password for root from 10.0.0.10 port 2222 ssh2",
            "srcip": "10.0.0.10",
            "srcuser": "root",
            "event_type": "ssh_auth_failure",
            "ground_truth_incident_id": "inc-2",
            "synthetic": True,
        },
    ]
    alerts = load_alerts_from_records(records, require_synthetic=True)
    result = run_iteration1(
        alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=DeterministicSummaryClient(),
    )
    assert result.output_item_count == 2


def test_iteration1_vector_store_backends_parity() -> None:
    records = generate_synthetic_wazuh_ssh_alerts()
    baseline = run_iteration1_from_records(records, vector_store_backend="in_memory")

    for backend in ("faiss", "chroma"):
        result = run_iteration1_from_records(records, vector_store_backend=backend)
        assert result.raw_alert_count == baseline.raw_alert_count
        assert result.output_item_count == baseline.output_item_count
        assert result.alert_reduction_ratio == baseline.alert_reduction_ratio
        assert result.cluster_purity == baseline.cluster_purity
        assert [c.count for c in result.clusters] == [c.count for c in baseline.clusters]
        assert all(bool(c.summary) for c in result.clusters)


def test_iteration1_invalid_vector_store_backend_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported vector store backend"):
        run_iteration1_from_records(generate_synthetic_wazuh_ssh_alerts(), vector_store_backend="invalid-backend")


def test_active_window_false_split_prevention() -> None:
    base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    records = []
    for i in range(10):
        records.append(
            {
                "timestamp": (base + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
                "rule": {"id": "5710", "description": "sshd authentication failed"},
                "full_log": f"sshd: Failed password for root from 10.0.0.77 port {2200+i} ssh2",
                "srcip": "10.0.0.77",
                "srcuser": "root",
                "event_type": "ssh_auth_failure",
                "ground_truth_incident_id": "inc-one",
                "synthetic": True,
            }
        )
    alerts = load_alerts_from_records(records, require_synthetic=True)
    result = run_iteration1(
        alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=DeterministicSummaryClient(),
    )
    assert result.output_item_count == 1
    assert result.clusters[0].count == 10
