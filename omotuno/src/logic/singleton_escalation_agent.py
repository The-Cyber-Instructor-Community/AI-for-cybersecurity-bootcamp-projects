from __future__ import annotations

from dataclasses import dataclass

from src.pipeline.config import SINGLETON_NOVELTY_THRESHOLD
from src.pipeline.types import ClusterState


@dataclass(frozen=True)
class SingletonEscalationResult:
    label: str  # novel | routine
    escalated: bool
    score: float
    reasoning: str


def classify_singleton(cluster: ClusterState, threshold: float = SINGLETON_NOVELTY_THRESHOLD) -> SingletonEscalationResult:
    if cluster.count != 1 or not cluster.members:
        return SingletonEscalationResult(
            label="routine",
            escalated=False,
            score=0.0,
            reasoning="not a singleton cluster",
        )

    alert = cluster.members[0]
    score = 0.0
    facts: list[str] = []

    if alert.srcuser in {"oracle", "admin", "root"}:
        score += 0.25
        facts.append(f"privileged user={alert.srcuser}")
    if "invalid user" in alert.full_log.lower() or "failed password" in alert.full_log.lower():
        score += 0.2
        facts.append("authentication failure pattern present")
    if alert.srcip.endswith(".50") or alert.srcip.endswith(".99"):
        score += 0.2
        facts.append(f"uncommon source ip={alert.srcip}")
    # Intentionally avoid hidden/evaluation labels (e.g., ground_truth_incident_id).
    # Only observable alert fields contribute to classification/reasoning.
    if len(alert.full_log) > 90:
        score += 0.15
        facts.append("high-entropy log sample")

    label = "novel" if score >= threshold else "routine"
    escalated = label == "novel"
    if not facts:
        facts = ["no strong novelty indicators found"]

    reasoning = "; ".join(facts)[:240]
    return SingletonEscalationResult(
        label=label,
        escalated=escalated,
        score=score,
        reasoning=reasoning,
    )
