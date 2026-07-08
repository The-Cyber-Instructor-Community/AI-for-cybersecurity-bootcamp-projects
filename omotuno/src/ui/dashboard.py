from __future__ import annotations

try:
    from src.logic.review_gate import get_action_descriptors
except ModuleNotFoundError:
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from src.logic.review_gate import get_action_descriptors


def _source_ip_display(cluster) -> str:
    return ",".join(sorted(cluster.distinct_srcips)) if len(cluster.distinct_srcips) <= 2 else str(len(cluster.distinct_srcips))


def build_dashboard_view_model(result) -> dict:
    rows = []
    for cluster in result.clusters:
        rows.append(
            {
                "cluster_id": cluster.cluster_id,
                "count": cluster.count,
                "first_seen": cluster.first_seen.isoformat(),
                "last_seen": cluster.last_seen.isoformat(),
                "time_span_seconds": int(cluster.time_span().total_seconds()),
                "source_ip": _source_ip_display(cluster),
                "summary": cluster.summary or "",
                "contradiction_detected": cluster.contradiction_detected,
                "backstop_reasons": cluster.backstop_reasons,
                "summary_stale": cluster.summary_stale,
                "summary_status": cluster.summary_status,
                "disposition": cluster.disposition,
                "reviewed_by": cluster.reviewed_by,
                "reviewed_at": cluster.reviewed_at,
                "superseded_by": cluster.superseded_by,
                "drift_detected": getattr(cluster, "drift_detected", False),
                "drift_score": getattr(cluster, "drift_score", 0.0),
                "drift_reason": getattr(cluster, "drift_reason", None),
                "drift_evidence": getattr(cluster, "drift_evidence", {}),
                "singleton_label": getattr(cluster, "singleton_label", None),
                "singleton_escalated": getattr(cluster, "singleton_escalated", False),
                "singleton_reasoning": getattr(cluster, "singleton_reasoning", None),
                "singleton_score": getattr(cluster, "singleton_score", 0.0),
                "raw_facts": {
                    "total_count": cluster.count,
                    "first_seen": cluster.first_seen.isoformat(),
                    "last_seen": cluster.last_seen.isoformat(),
                    "distinct_srcips": _source_ip_display(cluster),
                    "distinct_users": ",".join(sorted(cluster.distinct_users)) if len(cluster.distinct_users) <= 2 else str(len(cluster.distinct_users)),
                    "distinct_rule_ids": len(cluster.distinct_rule_ids),
                },
                "action_descriptors": get_action_descriptors(),
            }
        )

    review_queue = [
        row
        for row in rows
        if row["superseded_by"] is None and (row["disposition"] is None or row["contradiction_detected"])
    ]

    payload = {
        "before_count": result.raw_alert_count,
        "after_count": result.output_item_count,
        "reduction_ratio": result.alert_reduction_ratio,
        "cluster_rows": rows,
        "review_queue": review_queue,
        "unreviewed_count": len(review_queue),
    }

    if hasattr(result, "suppressed_alert_count"):
        payload["suppressed_alert_count"] = result.suppressed_alert_count
    if hasattr(result, "embedded_alert_count"):
        payload["embedded_alert_count"] = result.embedded_alert_count

    if hasattr(result, "drifted_clusters"):
        payload["drifted_clusters_count"] = len(result.drifted_clusters)
    if hasattr(result, "singleton_escalations"):
        payload["singleton_escalations_count"] = len(result.singleton_escalations)
    if hasattr(result, "recalibration_proposals"):
        payload["recalibration_proposals"] = [
            {
                "proposal_id": p.proposal_id,
                "status": p.status,
                "current_similarity_threshold": p.current_similarity_threshold,
                "proposed_similarity_threshold": p.proposed_similarity_threshold,
                "current_window_hours": p.current_window_hours,
                "proposed_window_hours": p.proposed_window_hours,
                "split_count": p.split_count,
                "merge_count": p.merge_count,
                "rationale": p.rationale,
                "risk_notes": p.risk_notes,
                "clamped": p.clamped,
                "reviewed_by": p.reviewed_by,
                "reviewed_at": p.reviewed_at,
                "rejection_reason": p.rejection_reason,
            }
            for p in result.recalibration_proposals
        ]
        payload["proposal_action_descriptors"] = [
            {"action": "approve_recalibration", "required_fields": ["reviewed_by"]},
            {"action": "reject_recalibration", "required_fields": ["reviewed_by"], "optional_fields": ["reason"]},
        ]
    if hasattr(result, "active_similarity_threshold"):
        payload["active_similarity_threshold"] = result.active_similarity_threshold
    if hasattr(result, "active_window_hours"):
        payload["active_window_hours"] = result.active_window_hours

    return payload


def render_dashboard(result, scenario_label: str | None = None, set_page: bool = True) -> None:
    try:
        import streamlit as st  # type: ignore
    except ImportError as exc:
        raise RuntimeError("streamlit is required to render dashboard") from exc

    if set_page:
        st.set_page_config(page_title="Sift Dashboard", layout="wide")

    model = build_dashboard_view_model(result)
    st.title("Sift Dashboard")
    if scenario_label:
        st.caption(f"Scenario: {scenario_label}")

    metric_items = [
        ("Before (Raw Alerts)", model["before_count"]),
        ("After (Clusters + Singletons)", model["after_count"]),
        ("Alert Reduction Ratio", f"{model['reduction_ratio']:.2f}"),
    ]
    if "suppressed_alert_count" in model:
        metric_items.append(("Suppressed Alerts", model["suppressed_alert_count"]))
    if "embedded_alert_count" in model:
        metric_items.append(("Embedded Alerts", model["embedded_alert_count"]))
    if "drifted_clusters_count" in model:
        metric_items.append(("Drifted Clusters", model["drifted_clusters_count"]))
    if "singleton_escalations_count" in model:
        metric_items.append(("Singleton Escalations", model["singleton_escalations_count"]))

    metric_cols = st.columns(len(metric_items))
    for col, (label, value) in zip(metric_cols, metric_items):
        col.metric(label, value)

    cluster_rows_display = []
    for row in model["cluster_rows"]:
        cluster_rows_display.append(
            {
                "cluster_id": row["cluster_id"],
                "count": row["count"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "time_span_seconds": row["time_span_seconds"],
                "source_ip": row["source_ip"],
                "summary": row["summary"],
                "summary_status": row["summary_status"],
                "contradiction_detected": "Yes" if row["contradiction_detected"] else "No",
                "disposition": row["disposition"] or "unreviewed",
                "drift_detected": "Yes" if row["drift_detected"] else "No",
                "drift_score": round(float(row["drift_score"]), 3),
                "drift_reason": row["drift_reason"] or "",
                "singleton_label": row["singleton_label"] or "",
                "singleton_escalated": "Yes" if row["singleton_escalated"] else "No",
            }
        )

    st.subheader("Cluster Rows")
    st.dataframe(cluster_rows_display, use_container_width=True, height=460)

    review_rows_display = []
    for row in model["review_queue"]:
        review_rows_display.append(
            {
                "cluster_id": row["cluster_id"],
                "count": row["count"],
                "summary_status": row["summary_status"],
                "contradiction_detected": "Yes" if row["contradiction_detected"] else "No",
                "disposition": row["disposition"] or "unreviewed",
                "reviewed_by": row["reviewed_by"] or "",
                "reviewed_at": row["reviewed_at"] or "",
            }
        )

    st.subheader("Review Queue")
    st.metric("Unreviewed Queue Count", model["unreviewed_count"])
    st.dataframe(review_rows_display, use_container_width=True, height=300)

    with st.expander("Advanced diagnostics (raw fields)", expanded=False):
        advanced_rows = []
        for row in model["cluster_rows"]:
            advanced_rows.append(
                {
                    "cluster_id": row["cluster_id"],
                    "backstop_reasons": ", ".join(row["backstop_reasons"]) if row["backstop_reasons"] else "",
                    "summary_stale": row["summary_stale"],
                    "drift_evidence": str(row["drift_evidence"]),
                    "raw_facts": str(row["raw_facts"]),
                    "action_descriptors": str(row["action_descriptors"]),
                }
            )
        st.dataframe(advanced_rows, use_container_width=True, height=260)


def _build_baseline_result():
    from src.pipeline.run_iteration3 import run_iteration3_from_records
    from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
    from src.store.review_store import InMemoryReviewStore

    review_store = InMemoryReviewStore()
    return run_iteration3_from_records(
        records=generate_synthetic_wazuh_ssh_alerts(),
        review_store=review_store,
    )


def _build_drift_demo_result():
    from src.pipeline.run_iteration3 import run_iteration3_from_records
    from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
    from src.store.review_store import InMemoryReviewStore

    records = generate_synthetic_wazuh_ssh_alerts()
    for idx in range(110, 150):
        records[idx]["full_log"] = (
            f"sshd: Failed password for root from 10.0.0.10 port {2200 + idx} ssh2 "
            "suspicious lateral movement command-and-control beacon token exfiltration persistence"
        )

    review_store = InMemoryReviewStore()
    review_store.log_action("split", "c-a", {"reviewed_by": "analyst@example.com"})
    review_store.log_action("split", "c-b", {"reviewed_by": "analyst@example.com"})
    return run_iteration3_from_records(
        records=records,
        review_store=review_store,
    )


def _build_injection_demo_result():
    from src.agents.embed_agent import DeterministicEmbeddingClient
    from src.logic.suppression import SuppressionEngine
    from src.pipeline.ingest import load_alerts_from_records
    from src.pipeline.run_iteration2 import run_iteration2
    from src.pipeline.synthetic import generate_adversarial_wazuh_ssh_alerts
    from src.store.suppression_store import InMemorySuppressionStore

    class PoisonedSummaryClient:
        def summarize(self, payload, model_id=None):
            return (
                f"{payload.total_count} SSH authentication alerts were grouped from {payload.first_seen} to "
                f"{payload.last_seen} with source IPs {payload.distinct_srcips}, likely routine and low priority."
            )

    alerts = load_alerts_from_records(generate_adversarial_wazuh_ssh_alerts(), require_synthetic=True)
    return run_iteration2(
        alerts=alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=PoisonedSummaryClient(),
        suppression_engine=SuppressionEngine(InMemorySuppressionStore()),
    )


def _build_suppression_volume_override_demo_result():
    from datetime import datetime, timedelta, timezone

    from src.agents.embed_agent import DeterministicEmbeddingClient
    from src.agents.summary_agent import DeterministicSummaryClient
    from src.logic.suppression import SuppressionEngine
    from src.pipeline.ingest import load_alerts_from_records
    from src.pipeline.run_iteration2 import run_iteration2
    from src.store.suppression_store import InMemorySuppressionStore, SuppressionRule

    base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    records: list[dict] = []

    for i in range(5):
        ts = base + timedelta(minutes=i)
        records.append(
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "rule": {"id": "5710", "description": "sshd authentication failed"},
                "full_log": f"sshd[{4000+i}]: Failed password for root from 10.9.0.10 port {2200+i} ssh2",
                "srcip": "10.9.0.10",
                "srcuser": "root",
                "event_type": "ssh_auth_failure",
                "ground_truth_incident_id": "sup-small",
                "synthetic": True,
            }
        )

    for i in range(7):
        ts = base + timedelta(minutes=30 + i)
        records.append(
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "rule": {"id": "5710", "description": "sshd authentication failed"},
                "full_log": f"sshd[{5000+i}]: Failed password for admin from 10.9.0.20 port {3300+i} ssh2",
                "srcip": "10.9.0.20",
                "srcuser": "admin",
                "event_type": "ssh_auth_failure",
                "ground_truth_incident_id": "sup-override",
                "synthetic": True,
            }
        )

    alerts = load_alerts_from_records(records, require_synthetic=True)
    suppression_store = InMemorySuppressionStore()
    expires = base + timedelta(days=1)
    suppression_store.upsert_rule(SuppressionRule(rule_id="5710", srcip="10.9.0.10", expires_at=expires, baseline_volume=2))
    suppression_store.upsert_rule(SuppressionRule(rule_id="5710", srcip="10.9.0.20", expires_at=expires, baseline_volume=2))

    suppression_engine = SuppressionEngine(suppression_store)
    return run_iteration2(
        alerts=alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=DeterministicSummaryClient(),
        suppression_engine=suppression_engine,
    )


def _build_stale_summary_demo_result():
    from datetime import datetime, timedelta, timezone

    from src.agents.embed_agent import DeterministicEmbeddingClient, embed_alert
    from src.agents.summary_agent import DeterministicSummaryClient
    from src.logic.clustering import assign_embedded_alert
    from src.logic.review_gate import open_cluster_for_review
    from src.logic.suppression import SuppressionEngine
    from src.pipeline.ingest import load_alerts_from_records
    from src.pipeline.run_iteration2 import run_iteration2
    from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
    from src.store.suppression_store import InMemorySuppressionStore

    alerts = load_alerts_from_records(generate_synthetic_wazuh_ssh_alerts(), require_synthetic=True)
    summary_client = DeterministicSummaryClient()
    result = run_iteration2(
        alerts=alerts,
        embedding_client=DeterministicEmbeddingClient(),
        summary_client=summary_client,
        suppression_engine=SuppressionEngine(InMemorySuppressionStore()),
    )

    target = result.clusters[0]
    target.is_closed = False
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    open_cluster_for_review(target, summary_client=summary_client, reviewed_at=now)

    new_alert = target.members[-1]
    joined_alert = type(new_alert)(
        **{
            **new_alert.__dict__,
            "alert_id": "late-join-ui-demo",
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
    return result


def _build_review_lifecycle_demo_result():
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

    c1, c2, c3, c4, c5 = result.clusters[0], result.clusters[1], result.clusters[2], result.clusters[3], result.clusters[4]

    confirm_cluster(c4, "analyst@example.com", now, review_store)
    dismiss_cluster(
        c5,
        "analyst@example.com",
        now,
        review_store,
        suppression_store=suppression_store,
        create_suppression=True,
        suppression_expires_at=now + timedelta(days=1),
    )
    escalate_cluster(c3, "analyst@example.com", now, "TICKET-99", review_store)

    midpoint = len(c1.members) // 2
    partitions = [
        [m.alert_id for m in c1.members[:midpoint]],
        [m.alert_id for m in c1.members[midpoint:]],
    ]
    new_clusters = split_cluster(
        c1,
        partitions,
        "analyst@example.com",
        now,
        DeterministicEmbeddingClient(),
        review_store,
    )
    merged = merge_clusters(new_clusters[0], new_clusters[1], "analyst@example.com", now, review_store)
    result.clusters.extend(new_clusters)
    result.clusters.append(merged)

    return result


def _build_recalibration_transition_demo_result():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from src.logic.recalibration_agent import ActiveCalibrationState
    from src.pipeline.config import SIMILARITY_THRESHOLD, WINDOW
    from src.pipeline.run_iteration3 import (
        approve_recalibration_proposal,
        reject_recalibration_proposal,
        run_iteration3_from_records,
    )
    from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
    from src.store.review_store import InMemoryReviewStore

    review_store = InMemoryReviewStore()
    review_store.log_action("merge", "c-a", {"reviewed_by": "analyst@example.com"})
    review_store.log_action("merge", "c-b", {"reviewed_by": "analyst@example.com"})

    state = ActiveCalibrationState(
        similarity_threshold=SIMILARITY_THRESHOLD,
        window_hours=int(WINDOW.total_seconds() // 3600),
    )

    initial = run_iteration3_from_records(
        records=generate_synthetic_wazuh_ssh_alerts(),
        review_store=review_store,
        active_calibration_state=state,
    )
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    rejected = reject_recalibration_proposal(
        proposal=initial.recalibration_proposals[0],
        reviewed_by="analyst@example.com",
        reviewed_at=now,
        reason="hold for extra evidence",
        review_store=review_store,
    )

    second = run_iteration3_from_records(
        records=generate_synthetic_wazuh_ssh_alerts(),
        review_store=review_store,
        active_calibration_state=state,
    )
    approved = approve_recalibration_proposal(
        proposal=second.recalibration_proposals[0],
        reviewed_by="analyst@example.com",
        reviewed_at=now,
        review_store=review_store,
        active_calibration_state=state,
    )

    return SimpleNamespace(
        raw_alert_count=second.raw_alert_count,
        suppressed_alert_count=second.suppressed_alert_count,
        embedded_alert_count=second.embedded_alert_count,
        clusters=second.clusters,
        singletons=second.singletons,
        output_item_count=second.output_item_count,
        alert_reduction_ratio=second.alert_reduction_ratio,
        cluster_purity=second.cluster_purity,
        review_queue=second.review_queue,
        drifted_clusters=second.drifted_clusters,
        singleton_escalations=second.singleton_escalations,
        recalibration_proposals=[rejected, approved],
        active_similarity_threshold=state.similarity_threshold,
        active_window_hours=state.window_hours,
    )


def run_dashboard_app() -> None:
    import streamlit as st  # type: ignore
    from pathlib import Path

    st.set_page_config(page_title="Sift Dashboard", layout="wide")
    scenario_image = Path(__file__).resolve().parents[2] / "docs" / "screenshots" / "06_demo_scenario_dropdown.png"
    if scenario_image.exists():
        st.sidebar.image(str(scenario_image), caption="Demo scenario selector reference")
    scenario = st.sidebar.selectbox(
        "Demo scenario",
        (
            "Baseline (Iteration 3 default)",
            "Drift-rich demo (Iteration 3)",
            "Injection-defense demo (Iteration 2)",
            "Suppression volume-override demo (Iteration 2)",
            "Stale summary cache demo (Iteration 2)",
            "Review lifecycle demo (Iteration 2)",
            "Recalibration transitions demo (Iteration 3)",
        ),
    )

    if scenario == "Drift-rich demo (Iteration 3)":
        result = _build_drift_demo_result()
    elif scenario == "Injection-defense demo (Iteration 2)":
        result = _build_injection_demo_result()
    elif scenario == "Suppression volume-override demo (Iteration 2)":
        result = _build_suppression_volume_override_demo_result()
    elif scenario == "Stale summary cache demo (Iteration 2)":
        result = _build_stale_summary_demo_result()
    elif scenario == "Review lifecycle demo (Iteration 2)":
        result = _build_review_lifecycle_demo_result()
    elif scenario == "Recalibration transitions demo (Iteration 3)":
        result = _build_recalibration_transition_demo_result()
    else:
        result = _build_baseline_result()

    render_dashboard(result, scenario_label=scenario, set_page=False)


if __name__ == "__main__":
    run_dashboard_app()
