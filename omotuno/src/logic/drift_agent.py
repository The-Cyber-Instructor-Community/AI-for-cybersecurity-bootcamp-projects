from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import mean

from src.pipeline.config import DRIFT_MIN_EVIDENCE, DRIFT_THRESHOLD
from src.pipeline.types import ClusterState


@dataclass(frozen=True)
class DriftResult:
    drift_detected: bool
    drift_score: float
    reason: str
    evidence: dict


def _token_set(text: str) -> set[str]:
    # Deterministic lexical proxy focused on observable text fields.
    return set(re.findall(r"[a-z]+", text.lower()))


def _jaccard_distance(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return 1.0 - (len(a & b) / len(union))


def evaluate_cluster_drift(
    cluster: ClusterState,
    threshold: float = DRIFT_THRESHOLD,
    min_evidence: int = DRIFT_MIN_EVIDENCE,
) -> DriftResult:
    if cluster.superseded_by is not None:
        return DriftResult(
            drift_detected=False,
            drift_score=0.0,
            reason="not_active",
            evidence={"count": cluster.count, "threshold": threshold},
        )

    if cluster.count < min_evidence or len(cluster.members) < min_evidence:
        return DriftResult(
            drift_detected=False,
            drift_score=0.0,
            reason="insufficient_evidence",
            evidence={"count": cluster.count, "min_evidence": min_evidence, "threshold": threshold},
        )

    reference = cluster.members[0]
    reference_tokens = _token_set(f"{reference.rule_description} {reference.full_log} {reference.srcuser}")
    distances: list[tuple[str, float]] = []
    for member in cluster.members[1:]:
        tokens = _token_set(f"{member.rule_description} {member.full_log} {member.srcuser}")
        d = _jaccard_distance(reference_tokens, tokens)
        distances.append((member.alert_id, d))

    only_distances = [d for _, d in distances]
    max_distance = max(only_distances)
    top_k = max(1, len(only_distances) // 4)
    top_k_mean = mean(sorted(only_distances, reverse=True)[:top_k])

    # Chained-drift-sensitive score: emphasize far-tail divergence while stabilizing by top-K mean.
    drift_score = (max_distance + top_k_mean) / 2.0
    detected = drift_score >= threshold
    reason = "centroid_drift" if detected else "within_threshold"

    farthest_alert_id = max(distances, key=lambda item: item[1])[0]
    return DriftResult(
        drift_detected=detected,
        drift_score=drift_score,
        reason=reason,
        evidence={
            "count": cluster.count,
            "threshold": threshold,
            "max_distance": max_distance,
            "top_k_mean_distance": top_k_mean,
            "reference_alert_id": reference.alert_id,
            "farthest_alert_id": farthest_alert_id,
        },
    )
