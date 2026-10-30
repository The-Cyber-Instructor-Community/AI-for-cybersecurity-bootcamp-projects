"""Stage 3: detections.

Two kinds of rule:
  * signature rules  - standard Sigma YAML files in rules/sigma, one event at a time
  * behavioural rule - BEH-001, a tactic SEQUENCE for one user inside 60 minutes
    (click external link -> sign in from new device -> enumerate domain groups
    -> read sensitive cloud storage). It catches attacks that stay under every
    single-event threshold.

The Sigma evaluator below supports the subset these rules use: field equality,
lists as OR, the modifiers contains / startswith / endswith / all / gte / gt /
lte / lt, and conditions built from selection names with and / or / not.
For a production SIEM you would convert the same YAML with pySigma instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import yaml

from .config import path, settings
from .schema import Event

TOP_LEVEL = {"id", "ts", "source", "event_type", "user", "host", "src_ip"}


@dataclass
class Alert:
    id: str
    rule_id: str
    title: str
    level: str
    kind: str                       # signature | behavioural
    techniques: list[str]
    ts: str
    user: str | None
    host: str | None
    event_ids: list[str] = field(default_factory=list)


@dataclass
class Rule:
    rule_id: str
    title: str
    level: str
    techniques: list[str]
    selections: dict
    condition: str
    file: str

    @classmethod
    def load(cls, p: Path) -> "Rule":
        y = yaml.safe_load(p.read_text(encoding="utf-8"))
        rid = p.stem.split("_")[0].upper() + "-" + p.stem.split("_")[1]
        return cls.from_dict(y, rid, p.name)

    @classmethod
    def from_dict(cls, y: dict, rule_id: str, file: str = "") -> "Rule":
        det = dict(y["detection"])
        cond = det.pop("condition")
        techs = [t.split(".", 1)[1].upper() for t in y.get("tags", []) if re.match(r"attack\.t\d", str(t))]
        return cls(rule_id=rule_id, title=y.get("title", rule_id), level=y.get("level", "medium"),
                   techniques=techs, selections=det, condition=cond, file=file)

    def matches(self, ev: Event) -> bool:
        results = {name: _selection(sel, ev) for name, sel in self.selections.items()}
        return _condition(self.condition, results)


def _value(ev: Event, name: str):
    return getattr(ev, name, None) if name in TOP_LEVEL else ev.fields.get(name)


def _selection(sel: dict, ev: Event) -> bool:
    for key, expected in sel.items():
        name, *mods = key.split("|")
        if not _match(_value(ev, name), expected, mods):
            return False
    return True


def _match(actual, expected, mods: list[str]) -> bool:
    if actual is None:
        return False
    want_all = "all" in mods
    options = expected if isinstance(expected, list) else [expected]
    hits = [_one(actual, e, mods) for e in options]
    return all(hits) if want_all else any(hits)


def _one(actual, expected, mods: list[str]) -> bool:
    for op, fn in (("gte", lambda a, b: a >= b), ("gt", lambda a, b: a > b),
                   ("lte", lambda a, b: a <= b), ("lt", lambda a, b: a < b)):
        if op in mods:
            try:
                return fn(float(actual), float(expected))
            except (TypeError, ValueError):
                return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected or str(actual).lower() == str(expected).lower()
    a, e = str(actual).lower(), str(expected).lower()
    if "contains" in mods:
        return e in a
    if "startswith" in mods:
        return a.startswith(e)
    if "endswith" in mods:
        return a.endswith(e)
    return a == e


def _condition(cond: str, results: dict) -> bool:
    tokens = re.findall(r"\(|\)|[A-Za-z_][A-Za-z0-9_]*", cond)
    expr = []
    for t in tokens:
        if t in ("and", "or", "not", "(", ")"):
            expr.append(t)
        elif t in results:
            expr.append(str(results[t]))
        else:
            raise ValueError(f"unknown name '{t}' in condition '{cond}'")
    return bool(eval(" ".join(expr), {"__builtins__": {}}, {}))  # only True/False/and/or/not/()


def load_rules(folder: Path | None = None) -> list[Rule]:
    folder = folder or path("rules_dir")
    return [Rule.load(p) for p in sorted(folder.glob("*.yml"))]


def run_signatures(events: list[Event], rules: list[Rule]) -> list[Alert]:
    alerts = []
    for ev in events:
        for r in rules:
            if r.matches(ev):
                alerts.append(Alert(id="", rule_id=r.rule_id, title=r.title, level=r.level,
                                    kind="signature", techniques=r.techniques, ts=ev.ts,
                                    user=ev.user, host=ev.host, event_ids=[ev.id]))
    return alerts


# ---- behavioural rule: tactic sequence -------------------------------------
BEH_STAGES = [
    ("T1566.002", lambda e: e.event_type == "email_link_click" and e.fields.get("sender_internal") is False),
    ("T1078.004", lambda e: e.event_type == "signin" and e.fields.get("device_new") is True),
    ("T1069.002", lambda e: e.event_type == "process_create"
        and all(w in str(e.fields.get("cmdline", "")).lower() for w in ("net", "group"))),
    ("T1530", lambda e: e.event_type == "object_access" and e.fields.get("bucket") == "finance-reports"
        and int(e.fields.get("object_count", 0)) >= 20),
]


def run_behavioural(events: list[Event], window_minutes: int = 60) -> list[Alert]:
    """BEH-001: all four stages, in order, by the same user, within the window."""
    by_user: dict[str, list[Event]] = {}
    for ev in events:
        if ev.user:
            by_user.setdefault(ev.user, []).append(ev)
    alerts, window = [], timedelta(minutes=window_minutes)
    for user, evs in by_user.items():
        starts = [e for e in evs if BEH_STAGES[0][1](e)]
        for s in starts:
            chain, t = [s], s.time
            for _, pred in BEH_STAGES[1:]:
                nxt = next((e for e in evs if t < e.time <= s.time + window and pred(e)), None)
                if not nxt:
                    break
                chain.append(nxt)
                t = nxt.time
            if len(chain) == len(BEH_STAGES):
                alerts.append(Alert(id="", rule_id="BEH-001",
                                    title="Tactic sequence: phish click -> new-device sign-in -> "
                                          "group discovery -> sensitive cloud read",
                                    level="high", kind="behavioural",
                                    techniques=[t for t, _ in BEH_STAGES], ts=s.ts, user=user,
                                    host=next((e.host for e in chain if e.host), None),
                                    event_ids=[e.id for e in chain]))
    return alerts


def detect(events: list[Event]) -> list[Alert]:
    win = settings()["pipeline"]["correlation_window_minutes"]
    alerts = run_signatures(events, load_rules()) + run_behavioural(events, win)
    alerts.sort(key=lambda a: a.ts)
    for n, a in enumerate(alerts, 1):
        a.id = f"A{n:05d}"
    return alerts
