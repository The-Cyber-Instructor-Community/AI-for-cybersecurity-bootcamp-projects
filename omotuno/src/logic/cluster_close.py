from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from src.logic.backstop import BackstopResult
from src.logic.clustering import cosine_similarity
from src.logic.time_window import is_cluster_eligible
from src.pipeline.types import ClusterState, SummaryInput


def _aggregate_display(values: set[str]) -> str:
    ordered = sorted(values)
    if len(ordered) <= 2:
        return ",".join(ordered)
    return str(len(ordered))


def build_summary_input(cluster: ClusterState) -> SummaryInput:
    # ADR-006 fixed-shape deterministic fallback for <3 alerts.
    first_alert = cluster.members[0]
    last_alert = cluster.members[-1]
    if len(cluster.members) >= 3:
        outlier_alert = max(cluster.members, key=lambda a: 1.0 - cosine_similarity(cluster.centroid, _embed_proxy(a)))
    elif len(cluster.members) == 2:
        outlier_alert = cluster.members[-1]
    else:
        outlier_alert = cluster.members[0]

    return SummaryInput(
        total_count=cluster.count,
        first_seen=cluster.first_seen.isoformat(),
        last_seen=cluster.last_seen.isoformat(),
        distinct_srcips=_aggregate_display(cluster.distinct_srcips),
        distinct_usernames=_aggregate_display(cluster.distinct_users),
        distinct_rule_ids=len(cluster.distinct_rule_ids),
        sample_first_log=first_alert.full_log,
        sample_last_log=last_alert.full_log,
        sample_outlier_log=outlier_alert.full_log,
    )


def _embed_proxy(alert) -> list[float]:
    # deterministic lightweight proxy vector for outlier selection from in-memory member text.
    text = f"{alert.rule_description} {alert.full_log}"
    total = sum(ord(ch) for ch in text)
    return [
        float((total % 97) / 97.0),
        float((total % 89) / 89.0),
        float((total % 83) / 83.0),
        float((total % 79) / 79.0),
        float((total % 73) / 73.0),
        float((total % 71) / 71.0),
        float((total % 67) / 67.0),
        float((total % 61) / 61.0),
    ]


def _apply_summary_with_optional_backstop(
    cluster: ClusterState,
    payload: SummaryInput,
    summary_builder: Callable[[SummaryInput], str],
    backstop_checker: Callable[[SummaryInput, str], BackstopResult] | None,
    generated_at: datetime,
) -> None:
    candidate = summary_builder(payload)
    cluster.summary_generated_at = generated_at.isoformat()
    cluster.summary_stale = False

    if backstop_checker is None:
        cluster.summary = candidate
        cluster.summary_status = "ok"
        cluster.contradiction_detected = False
        cluster.backstop_reasons = []
        return

    result = backstop_checker(payload, candidate)
    if result.passed:
        cluster.summary = candidate
        cluster.summary_status = "ok"
        cluster.contradiction_detected = False
        cluster.backstop_reasons = []
    else:
        cluster.summary = "contradiction detected"
        cluster.summary_status = "contradiction_detected"
        cluster.contradiction_detected = True
        cluster.backstop_reasons = result.reason_codes


def regenerate_summary_if_stale_or_missing(
    cluster: ClusterState,
    summary_builder: Callable[[SummaryInput], str],
    backstop_checker: Callable[[SummaryInput, str], BackstopResult] | None = None,
    generated_at: datetime | None = None,
) -> bool:
    if cluster.summary is not None and not cluster.summary_stale:
        return False
    when = generated_at or datetime.utcnow()
    payload = build_summary_input(cluster)
    _apply_summary_with_optional_backstop(cluster, payload, summary_builder, backstop_checker, when)
    return True


def close_eligible_clusters(
    clusters: list[ClusterState],
    t_now: datetime,
    window: timedelta,
    summary_builder,
    force_close_all: bool = False,
    backstop_checker: Callable[[SummaryInput, str], BackstopResult] | None = None,
) -> int:
    """
    ADR-005 close-trigger path for Iteration 1/2.
    ADR-003 batch replay semantics: caller provides batch-relative t_now.
    """
    closed_count = 0
    for cluster in clusters:
        if cluster.is_closed:
            continue
        should_close = force_close_all or (not is_cluster_eligible(t_now, cluster.last_seen, window))
        if should_close:
            regenerate_summary_if_stale_or_missing(
                cluster=cluster,
                summary_builder=summary_builder,
                backstop_checker=backstop_checker,
                generated_at=t_now,
            )
            cluster.is_closed = True
            closed_count += 1
    return closed_count
