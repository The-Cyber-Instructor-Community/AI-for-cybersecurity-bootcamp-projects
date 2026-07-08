from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.embed_agent import DeterministicEmbeddingClient
from src.agents.summary_agent import DeterministicSummaryClient
from src.logic.suppression import SuppressionEngine
from src.pipeline.ingest import load_alerts_from_records
from src.pipeline.run_iteration2 import run_iteration2, run_iteration2_from_records
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.store.suppression_store import InMemorySuppressionStore, SuppressionRule


def test_iteration2_end_to_end_ordering_with_suppression_before_embed() -> None:
    records = generate_synthetic_wazuh_ssh_alerts()
    alerts = load_alerts_from_records(records, require_synthetic=True)

    first = alerts[0]
    store = InMemorySuppressionStore()
    store.upsert_rule(
        SuppressionRule(
            rule_id=first.rule_id,
            srcip=first.srcip,
            expires_at=first.timestamp + timedelta(days=1),
            baseline_volume=100,
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

    assert result.raw_alert_count == 200
    assert result.suppressed_alert_count > 0
    assert result.embedded_alert_count == 200 - result.suppressed_alert_count
    assert len(embed_client.calls) == result.embedded_alert_count
    assert result.output_item_count >= 1
    assert len(result.review_queue) >= 1


def test_iteration2_from_records_sqlite_suppression_default_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = run_iteration2_from_records(
        records=generate_synthetic_wazuh_ssh_alerts(),
        use_sqlite_suppression=True,
    )
    assert result.raw_alert_count == 200
    assert result.output_item_count >= 1
