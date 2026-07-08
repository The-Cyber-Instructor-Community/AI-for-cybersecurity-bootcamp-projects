from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.pipeline.config import SUPPRESSION_VOLUME_MULTIPLIER
from src.pipeline.types import AlertRecord
from src.store.suppression_store import SuppressionRule


@dataclass(frozen=True)
class SuppressionDecision:
    suppressed: bool
    reason: str
    matched_rule: SuppressionRule | None


class SuppressionEngine:
    def __init__(self, store, volume_multiplier: int = SUPPRESSION_VOLUME_MULTIPLIER) -> None:
        self.store = store
        self.volume_multiplier = volume_multiplier
        self.audit_log: list[dict] = []

    def decide(self, alert: AlertRecord, observed_volume: int, now: datetime) -> SuppressionDecision:
        rule = self.store.get_rule(alert.rule_id, alert.srcip)
        if rule is None:
            decision = SuppressionDecision(False, "no_match", None)
            self._audit(alert, decision, observed_volume)
            return decision

        if rule.expires_at < now:
            decision = SuppressionDecision(False, "expired", rule)
            self._audit(alert, decision, observed_volume)
            return decision

        threshold = rule.baseline_volume * self.volume_multiplier
        # Boundary decision (documented): suppress when observed_volume <= 3x baseline; bypass only above 3x.
        if observed_volume > threshold:
            decision = SuppressionDecision(False, "volume_override", rule)
            self._audit(alert, decision, observed_volume)
            return decision

        decision = SuppressionDecision(True, "suppressed", rule)
        self._audit(alert, decision, observed_volume)
        return decision

    def _audit(self, alert: AlertRecord, decision: SuppressionDecision, observed_volume: int) -> None:
        self.audit_log.append(
            {
                "alert_id": alert.alert_id,
                "rule_id": alert.rule_id,
                "srcip": alert.srcip,
                "decision": decision.reason,
                "suppressed": decision.suppressed,
                "observed_volume": observed_volume,
                "expires_at": decision.matched_rule.expires_at.isoformat() if decision.matched_rule else None,
                "baseline_volume": decision.matched_rule.baseline_volume if decision.matched_rule else None,
            }
        )
