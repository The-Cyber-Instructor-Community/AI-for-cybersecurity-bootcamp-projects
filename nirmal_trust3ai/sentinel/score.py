"""Score Sentinel's findings against a target's answer key (planted flaws).

A planted flaw counts as FOUND when some finding has the same check family and
covers one of the flaw's locations (same file, and the key line falls inside the
finding's line range, +/- 1 line).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from sentinel.models import Finding


def _covers(f: Finding, loc: dict) -> bool:
    end = f.end_line or f.line
    return f.file == loc["file"] and f.line - 1 <= loc["line"] <= end + 1


def score(findings: list[Finding], answer_key: str | Path) -> dict:
    key = yaml.safe_load(Path(answer_key).read_text())
    per_flaw, matched_findings = {}, set()
    for flaw in key["flaws"]:
        hits = [f.id for f in findings if f.check_family == flaw["check_family"]
                and any(_covers(f, loc) for loc in flaw["locations"])]
        per_flaw[flaw["id"]] = hits
        matched_findings.update(hits)
    found = sum(1 for h in per_flaw.values() if h)
    return {
        "found": found,
        "total": len(per_flaw),
        "recall": found / len(per_flaw),
        "precision": len(matched_findings) / len(findings) if findings else 0.0,
        "per_flaw": per_flaw,
        "unmatched_findings": [f.id for f in findings if f.id not in matched_findings],
    }


# --------------------------------------------------------------------------------------------
# Posture scoring: for apps with NO answer key (i.e. real/unknown apps).
#
# You cannot measure recall/precision without ground truth, so this does NOT score Sentinel's
# accuracy. Instead it scores the APP's security posture from what Sentinel found: a
# severity-weighted grade, a confidence per weakness, and how much of the app was analysed.
# --------------------------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path

from sentinel.kb import loader as _loader
from sentinel.models import Finding as _Finding

_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_DEDUCT = {"critical": 25, "high": 15, "medium": 7, "low": 3}   # points off a 100 baseline, per open weakness


def _grade(score: int) -> str:
    return next(g for cutoff, g in [(90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F")] if score >= cutoff)


def _confidence(worst_case, triages: list[str], statuses: list[str] | None = None) -> str:
    """How sure are we this weakness is real, without ground truth?"""
    if statuses and "confirmed" in statuses:
        return "confirmed (dynamic probe)"            # auto-probe fired - strongest
    if worst_case is True:
        return "confirmed (weak-model exploit)"       # dynamic proof
    if "confirmed" in triages:
        return "llm-confirmed"
    if triages and all(t == "disputed" for t in triages):
        return "llm-disputed (needs human review)"
    return "rule-only"


def posture(out_dir: str | _Path) -> dict:
    """Security-posture score for an app with no answer key. Reads runs/<app>/."""
    out = _Path(out_dir)
    findings = [_Finding(**f) for f in _json.loads((out / "findings.json").read_text())]
    smap = _json.loads((out / "system_map.json").read_text()) if (out / "system_map.json").exists() else {}
    report = _json.loads((out / "report.json").read_text()) if (out / "report.json").exists() else None
    worst_by_family = {w["family"]: w.get("worst_case_exploitable") for w in (report or {}).get("weaknesses", [])}

    weaknesses = []
    for fam in sorted({f.check_family for f in findings}):
        fam_findings = [f for f in findings if f.check_family == fam]
        severity = min((f.severity for f in fam_findings), key=lambda s: _SEV_RANK[s])
        weaknesses.append({
            "family": fam,
            "name": _loader.families()[fam]["name"],
            "severity": severity,
            "finding_count": len(fam_findings),
            "confidence": _confidence(worst_by_family.get(fam), [f.triage for f in fam_findings],
                                      [f.status for f in fam_findings]),
        })

    score = max(0, 100 - sum(_DEDUCT[w["severity"]] for w in weaknesses))
    by_sev = {s: sum(1 for w in weaknesses if w["severity"] == s) for s in _SEV_RANK}
    coverage = {k: len(smap.get(k, [])) for k in ("files", "llm_calls", "prompts", "tools", "agents", "edges")}
    return {
        "mode": "posture",
        "note": "No answer key: this scores the app's risk, not Sentinel's accuracy.",
        "risk_score": score,
        "grade": _grade(score),
        "weaknesses_by_severity": by_sev,
        "weaknesses": weaknesses,
        "coverage": coverage,
        "dynamically_tested": bool(report and report["summary"].get("dynamically_tested")),
    }
