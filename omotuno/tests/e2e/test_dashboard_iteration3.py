from __future__ import annotations

from src.pipeline.run_iteration3 import run_iteration3_from_records
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.store.review_store import InMemoryReviewStore
from src.ui.dashboard import build_dashboard_view_model


def test_dashboard_iteration3_visibility_and_regression_states() -> None:
    review_store = InMemoryReviewStore()
    review_store.log_action("split", "c-a", {"reviewed_by": "analyst@example.com"})
    review_store.log_action("split", "c-b", {"reviewed_by": "analyst@example.com"})

    result = run_iteration3_from_records(
        records=generate_synthetic_wazuh_ssh_alerts(),
        review_store=review_store,
    )
    model = build_dashboard_view_model(result)

    assert "review_queue" in model
    assert "unreviewed_count" in model
    assert model["unreviewed_count"] == len(model["review_queue"])
    assert "drifted_clusters_count" in model
    assert "singleton_escalations_count" in model
    assert "recalibration_proposals" in model
    assert "proposal_action_descriptors" in model
    assert "active_similarity_threshold" in model
    assert "active_window_hours" in model

    first_row = model["cluster_rows"][0]
    assert "contradiction_detected" in first_row
    assert "summary_stale" in first_row
    assert "drift_detected" in first_row
    assert "drift_score" in first_row
    assert "drift_reason" in first_row
    assert "singleton_label" in first_row
    assert "singleton_reasoning" in first_row
