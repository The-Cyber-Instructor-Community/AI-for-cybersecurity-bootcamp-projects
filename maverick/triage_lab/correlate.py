"""Stage 4: TTP correlation.

Groups alerts that belong together into one incident: same user, and each alert
within `correlation_window_minutes` of the previous one. Each incident then gets
  * its ATT&CK techniques and kill-chain stages, in time order
  * whether the stages progress in kill-chain order
  * a 0..1 risk score: alert severity + a bonus for every new stage reached,
    so a chain that advances scores higher than many alerts of one kind.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import settings
from .detections import Alert

LEVEL = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class Incident:
    id: str
    user: str
    start: str
    end: str
    alert_ids: list[str]
    rules: list[str]
    techniques: list[str]            # in first-seen order
    stages: list[int]                # kill-chain stage per technique, same order
    in_order: bool
    risk: float
    event_ids: list[str] = field(default_factory=list)


def correlate(alerts: list[Alert]) -> list[Incident]:
    cfg = settings()
    window = timedelta(minutes=cfg["pipeline"]["correlation_window_minutes"])
    stage_of = cfg["attack"]["chain_stage"]

    groups: list[list[Alert]] = []
    last_seen: dict[str, tuple[datetime, int]] = {}
    for a in sorted(alerts, key=lambda a: a.ts):
        t = datetime.fromisoformat(a.ts)
        key = a.user or a.host or "unknown"
        if key in last_seen and t - last_seen[key][0] <= window:
            idx = last_seen[key][1]
            groups[idx].append(a)
        else:
            groups.append([a])
            idx = len(groups) - 1
        last_seen[key] = (t, idx)

    incidents = []
    for n, g in enumerate(groups, 1):
        techs: list[str] = []
        for a in g:
            for t in a.techniques:
                if t not in techs:
                    techs.append(t)
        stages = [stage_of.get(t, 0) for t in techs]
        signature_stages = [stage_of.get(t, 0) for a in g if a.kind == "signature" for t in a.techniques]
        in_order = all(x <= y for x, y in zip(signature_stages, signature_stages[1:]))
        severity = sum(max(LEVEL.get(a.level, 2) for a in g if t in a.techniques) for t in techs)
        progression = 2 * (len(set(stages)) - 1)
        behavioural = 3 if any(a.kind == "behavioural" for a in g) else 0
        score = severity + progression + behavioural
        ev_ids = sorted({e for a in g for e in a.event_ids})
        incidents.append(Incident(
            id=f"INC-{n:04d}", user=g[0].user or "unknown", start=g[0].ts, end=g[-1].ts,
            alert_ids=[a.id for a in g], rules=sorted({a.rule_id for a in g}), techniques=techs,
            stages=stages, in_order=in_order, risk=round(1 - math.exp(-score / 8), 3),
            event_ids=ev_ids))
    return incidents
