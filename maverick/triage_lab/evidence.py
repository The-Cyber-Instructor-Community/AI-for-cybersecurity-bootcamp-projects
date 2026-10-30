"""Stage 5a: build the evidence bundle the AI reads for one incident.

Deterministic Python gathers the evidence; the AI only reasons over it. That is
deliberate: small local models are unreliable at driving their own tool calls.

Two modes, compared in the payload-vs-evidence ablation:
  payload   only the events that fired alerts
  evidence  those events plus related events for the same user or host within
            `context_padding_minutes` either side (what an analyst would pull)
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta

from .config import path, settings
from .context import Baseline, assets_for
from .correlate import Incident
from .detections import Alert
from .log_quality import LogQuality
from .rag import Retriever
from .schema import Event


def load_user_context() -> dict:
    with open(path("data_dir") / "users.csv", encoding="utf-8") as fh:
        return {r["user"]: r for r in csv.DictReader(fh)}


def build_bundle(inc: Incident, alerts_by_id: dict[str, Alert], events: list[Event],
                 events_by_id: dict[str, Event], lq: LogQuality, users: dict,
                 retriever: Retriever | None, *, mode: str = "evidence",
                 with_context: bool = True, baseline: Baseline | None = None) -> dict:
    cfg = settings()["pipeline"]
    pad = timedelta(minutes=cfg["context_padding_minutes"])
    start, end = datetime.fromisoformat(inc.start) - pad, datetime.fromisoformat(inc.end) + pad
    alerted = [events_by_id[e] for e in inc.event_ids if e in events_by_id]

    chosen = list(alerted)
    if mode == "evidence":
        hosts = {e.host for e in alerted if e.host}
        related = [e for e in events if start <= e.time <= end and e.id not in inc.event_ids
                   and (e.user == inc.user or (e.host and e.host in hosts))]
        chosen += related[: max(0, cfg["max_bundle_events"] - len(chosen))]
    chosen.sort(key=lambda e: e.ts)

    alerts = [alerts_by_id[a] for a in inc.alert_ids]
    knowledge = []
    if retriever:
        query = " ".join([a.title for a in alerts] + inc.techniques)
        knowledge = [{"doc": c.doc, "section": c.heading, "text": c.text}
                     for c in retriever.search(query, settings()["agent"]["rag_top_k"])]

    ctx = users.get(inc.user) if with_context else None
    gate_ctx = gate_context(inc, alerted, events, baseline)
    show_relevance = mode == "evidence"
    return {
        "incident_id": inc.id,
        "user": inc.user,
        "risk": inc.risk,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "alerts": [{"alert_id": a.id, "rule": a.rule_id, "title": a.title, "level": a.level,
                    "techniques": a.techniques, "event_ids": a.event_ids} for a in alerts],
        "events": [e.compact() for e in chosen],
        "log_health": lq.window_scores(start, end),
        "user_context": {k: v for k, v in ctx.items() if k != "user"} if ctx else None,
        "knowledge": knowledge,
        "assets": gate_ctx["assets"] if show_relevance else None,
        "baseline": gate_ctx["baseline"] if show_relevance else None,
        "gate_context": gate_ctx,          # computed by code for the gates; never shown to the AI
        "mode": mode,
    }


def gate_context(inc: Incident, alerted: list[Event], events: list[Event], baseline: Baseline | None) -> dict:
    baseline = baseline or Baseline(events)
    return {"assets": assets_for(alerted),
            "baseline": baseline.for_incident(inc.user, datetime.fromisoformat(inc.start), alerted)}
