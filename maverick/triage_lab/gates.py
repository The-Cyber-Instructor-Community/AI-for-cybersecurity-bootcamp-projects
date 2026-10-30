"""Stage 6b: the gates. Trusted code decides whether the AI may close.

The AI can only RECOMMEND "close". The incident is closed only if every gate
passes; otherwise it goes to a human with the list of reasons.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .config import settings
from .evidence import load_user_context


@lru_cache(maxsize=1)
def _users() -> dict:
    return load_user_context()


def injection_hits(bundle: dict) -> list[str]:
    """Event IDs whose field values contain text addressed to an AI."""
    pats = [re.compile(p) for p in settings()["gates"]["injection_patterns"]]
    hits = []
    for e in bundle["events"]:
        text = " ".join(str(v) for v in e.values())
        if any(p.search(text) for p in pats):
            hits.append(e["id"])
    return hits


def chain_tactics(bundle: dict) -> list[str]:
    tactic = settings()["attack"]["tactic"]
    return sorted({tactic[t] for a in bundle.get("alerts", []) for t in a.get("techniques", []) if t in tactic})


def apply_gates(verdict: dict | None, check: dict | None, bundle: dict,
                version: str | None = None) -> tuple[str, list[str]]:
    """version: 'v1' = the original gates; 'v2' adds the multi-stage chain gate. Default: settings."""
    g = settings()["gates"]
    version = version or g.get("controls_version", "v1")
    required = settings()["pipeline"]["required_sources"]
    if verdict is None:
        return "escalate", ["AI output was not valid JSON"]
    if verdict["decision"] == "escalate":
        return "escalate", []

    reasons = []
    unhealthy = [s for s in required if bundle["log_health"].get(s, 0) < g["log_quality_min"]]
    if unhealthy:
        reasons.append(f"degraded telemetry: {', '.join(unhealthy)} below {g['log_quality_min']}")
    # the gate reads the identity record itself, even when the AI was not shown it
    ctx = _users().get(bundle["user"], {})
    if g["never_close_privileged"] and ctx.get("privileged") == "yes":
        reasons.append("privileged identity: never auto-closed")
    if check and not check["passed"]:
        reasons.append("unsupported evidence: " + "; ".join(check["failures"][:2]))
    if check and check["observation_ratio"] < g["observation_ratio_min"]:
        reasons.append(f"inference-heavy verdict: observation ratio {check['observation_ratio']} "
                       f"< {g['observation_ratio_min']}")
    unknowns = [str(x) for x in verdict.get("not_determinable") or [] if str(x).strip()]
    if g.get("escalate_on_not_determinable", True) and unknowns:
        reasons.append(f"not determinable: {unknowns[0][:80]}")
    gc = bundle.get("gate_context") or {}
    if g.get("crown_jewel_first_seen", True):
        jewels = [a for a, rec in (gc.get("assets") or {}).items() if rec.get("crown_jewel") == "yes"]
        new = [c for c in (gc.get("baseline") or {}).get("first_seen_checks", []) if not c["seen_before"]]
        if jewels and new:
            reasons.append(f"crown-jewel asset {jewels[0]} with first-seen behaviour: {new[0]['value']}")
    if version >= "v2" and g.get("multi_stage_min_tactics"):
        tactics = chain_tactics(bundle)
        if len(tactics) >= g["multi_stage_min_tactics"]:
            reasons.append(f"multi-stage chain: {len(tactics)} ATT&CK tactics ({', '.join(tactics)})")
    if bundle.get("risk", 0) > g["max_risk_to_close"]:
        reasons.append(f"high-risk incident: risk {bundle['risk']} > {g['max_risk_to_close']}")
    if g["injection_guard"]:
        hits = injection_hits(bundle)
        if hits:
            reasons.append(f"possible prompt injection in evidence: {', '.join(hits[:3])}")
    if verdict["confidence"] < g["confidence_min_to_close"]:
        reasons.append(f"low confidence {verdict['confidence']} < {g['confidence_min_to_close']}")
    return ("escalate", reasons) if reasons else ("close", [])
