from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.pipeline.run_iteration1 import run_iteration1_from_records
from src.ui.dashboard import build_dashboard_view_model

result = run_iteration1_from_records(generate_synthetic_wazuh_ssh_alerts())
model = build_dashboard_view_model(result)

print({
    "raw_alert_count": result.raw_alert_count,
    "output_item_count": result.output_item_count,
    "singletons": len(result.singletons),
    "cluster_counts": [c.count for c in result.clusters],
    "cluster_purity": round(result.cluster_purity, 4),
    "alert_reduction_ratio": round(result.alert_reduction_ratio, 4),
    "dashboard_before": model["before_count"],
    "dashboard_after": model["after_count"],
    "summaries_present": all(bool(c.summary) for c in result.clusters),
})