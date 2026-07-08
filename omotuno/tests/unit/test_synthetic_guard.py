from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.embed_agent import DeterministicEmbeddingClient
from src.agents.summary_agent import DeterministicSummaryClient
from src.pipeline.ingest import load_alerts_from_records
from src.pipeline.run_iteration1 import run_iteration1, run_iteration1_from_records
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.pipeline.types import AlertRecord


def test_non_synthetic_rejected_by_loader() -> None:
    records = generate_synthetic_wazuh_ssh_alerts()
    records[0]["synthetic"] = False
    with pytest.raises(ValueError, match="non-synthetic"):
        load_alerts_from_records(records, require_synthetic=True)


def test_missing_ground_truth_marked_non_evaluable() -> None:
    records = generate_synthetic_wazuh_ssh_alerts()
    records[0].pop("ground_truth_incident_id")
    with pytest.raises(ValueError, match="ground_truth_incident_id"):
        run_iteration1_from_records(records, use_live_bedrock=False)


def test_core_runner_rejects_unlabeled_alerts() -> None:
    alert = AlertRecord(
        alert_id="direct-unlabeled",
        timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
        rule_id="5710",
        rule_description="sshd authentication failed",
        full_log="sshd: Failed password for root from 10.0.0.1 port 22 ssh2",
        srcip="10.0.0.1",
        srcuser="root",
        ground_truth_incident_id=None,
    )
    with pytest.raises(ValueError, match="ground_truth_incident_id"):
        run_iteration1(
            [alert],
            embedding_client=DeterministicEmbeddingClient(),
            summary_client=DeterministicSummaryClient(),
        )
