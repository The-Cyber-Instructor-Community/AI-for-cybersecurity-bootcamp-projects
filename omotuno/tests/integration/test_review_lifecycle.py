from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.embed_agent import DeterministicEmbeddingClient
from src.agents.summary_agent import DeterministicSummaryClient
from src.logic.review_gate import (
    confirm_cluster,
    dismiss_cluster,
    escalate_cluster,
    merge_clusters,
    split_cluster,
)
from src.logic.suppression import SuppressionEngine
from src.pipeline.ingest import load_alerts_from_records
from src.pipeline.run_iteration2 import run_iteration2
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.store.review_store import InMemoryReviewStore
from src.store.suppression_store import InMemorySuppressionStore


def test_review_actions_write_metadata_and_audit_entries() -> None:
    alerts = load_alerts_from_records(generate_synthetic_wazuh_ssh_alerts(), require_synthetic=True)
    result = run_iteration2(
        alerts=alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=DeterministicSummaryClient(),
        suppression_engine=SuppressionEngine(InMemorySuppressionStore()),
    )

    review_store = InMemoryReviewStore()
    suppression_store = InMemorySuppressionStore()
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    c1, c2, c3 = result.clusters[0], result.clusters[1], result.clusters[2]

    confirm_cluster(c1, "analyst@example.com", now, review_store)
    dismiss_cluster(
        c2,
        "analyst@example.com",
        now,
        review_store,
        suppression_store=suppression_store,
        create_suppression=True,
        suppression_expires_at=now + timedelta(days=1),
    )
    escalate_cluster(c3, "analyst@example.com", now, "TICKET-99", review_store)

    split_source = result.clusters[3]
    part1 = [split_source.members[0].alert_id]
    part2 = [split_source.members[-1].alert_id] if len(split_source.members) > 1 else [split_source.members[0].alert_id + "-missing"]
    # Ensure valid split for available members
    if len(split_source.members) == 1:
        # create a synthetic second member by using another singleton cluster member id from result if possible
        other = result.clusters[4].members[0]
        split_source.members.append(other)
        split_source.count = 2
        split_source.last_seen = other.timestamp
        split_source.distinct_srcips.add(other.srcip)
        split_source.distinct_users.add(other.srcuser)
        split_source.distinct_rule_ids.add(other.rule_id)
        part2 = [other.alert_id]

    new_clusters = split_cluster(
        split_source,
        [part1, part2],
        "analyst@example.com",
        now,
        DeterministicEmbeddingClient(),
        review_store,
    )
    merged = merge_clusters(new_clusters[0], new_clusters[1], "analyst@example.com", now, review_store)

    assert c1.disposition == "confirmed"
    assert c2.disposition == "dismissed"
    assert c3.disposition == "escalated"
    assert split_source.disposition == "split"
    assert merged.count == new_clusters[0].count + new_clusters[1].count
    assert len(review_store.entries) >= 5
