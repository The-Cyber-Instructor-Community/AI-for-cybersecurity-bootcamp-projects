from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.embed_agent import DeterministicEmbeddingClient
from src.agents.summary_agent import DeterministicSummaryClient
from src.logic.suppression import SuppressionEngine
from src.pipeline.ingest import load_alerts_from_records
from src.pipeline.run_iteration2 import run_iteration2
from src.store.suppression_store import InMemorySuppressionStore, SuppressionRule


def test_suppression_lookup_happens_before_embed_via_embed_spy() -> None:
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    records = [
        {
            "timestamp": base.isoformat().replace("+00:00", "Z"),
            "rule": {"id": "5710", "description": "sshd authentication failed"},
            "full_log": "sshd: Failed password for root from 10.0.0.10 port 22 ssh2",
            "srcip": "10.0.0.10",
            "srcuser": "root",
            "event_type": "ssh_auth_failure",
            "ground_truth_incident_id": "inc-1",
            "synthetic": True,
        },
        {
            "timestamp": (base + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "rule": {"id": "5710", "description": "sshd authentication failed"},
            "full_log": "sshd: Failed password for root from 10.0.0.11 port 23 ssh2",
            "srcip": "10.0.0.11",
            "srcuser": "root",
            "event_type": "ssh_auth_failure",
            "ground_truth_incident_id": "inc-2",
            "synthetic": True,
        },
    ]
    alerts = load_alerts_from_records(records, require_synthetic=True)

    store = InMemorySuppressionStore()
    store.upsert_rule(
        SuppressionRule(
            rule_id="5710",
            srcip="10.0.0.10",
            expires_at=base + timedelta(hours=1),
            baseline_volume=1,
        )
    )
    suppression_engine = SuppressionEngine(store)
    embed_client = DeterministicEmbeddingClient()
    summary_client = DeterministicSummaryClient()

    result = run_iteration2(
        alerts=alerts,
        embedding_client=embed_client,
        summary_client=summary_client,
        suppression_engine=suppression_engine,
    )

    assert result.raw_alert_count == 2
    assert result.suppressed_alert_count == 1
    assert result.embedded_alert_count == 1
    assert len(embed_client.calls) == 1
    # Verify suppressed alert id was audited as suppressed
    suppressed_ids = [entry["alert_id"] for entry in suppression_engine.audit_log if entry["suppressed"]]
    assert suppressed_ids == ["alert-0"]
