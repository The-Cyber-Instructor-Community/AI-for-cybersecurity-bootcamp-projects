"""Reporting agent - produces a MODEL-INDEPENDENT structural weakness report.

Core idea: a vulnerability is a missing guardrail in the app's code, not "the model got
tricked". So each report entry separates two things:

  * Structural weakness (model-independent): a static finding = a required control is missing
    from the code (see kb/controls.yaml). This is true no matter which model runs.
  * Worst-case exploitability (model-independent too): we confirm the flaw with the deliberately
    WEAK fake model. If the weakest plausible model can exploit it, a real/future/jailbroken model
    could as well - so the risk does not depend on today's strong model happening to refuse.
  * Current-model resistance (model-DEPENDENT, informational): if a real-model attack run exists,
    we note whether it resisted - but we never treat that as a fix.

A weakness is only "resolved" when the CODE adds the control and the weak model can no longer
exploit it (that check is the Fix-and-Verify step, Day 4).
"""
from __future__ import annotations

import json
from pathlib import Path

from sentinel.agents import redteam
from sentinel.harness import sandbox
from sentinel.kb import loader
from sentinel.models import AttackResult, Finding, Threat

SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _worst_case(target_dir: Path) -> dict[int, list[AttackResult]]:
    """Run the attacks against the WEAK fake model. Family -> results. Deterministic, free."""
    threats_file = Path("runs") / target_dir.name / "threats.json"
    findings_file = Path("runs") / target_dir.name / "findings.json"
    threats = [Threat(**t) for t in json.loads(threats_file.read_text())]
    findings = [Finding(**f) for f in json.loads(findings_file.read_text())]
    plan = redteam.select(threats, findings)
    results = redteam.run_plan(plan, backend="local", llm_backend="fake")
    by_family: dict[int, list[AttackResult]] = {}
    for r in results:
        by_family.setdefault(r.check_family, []).append(r)
    return by_family


def _current_model(out: Path) -> dict[int, list[AttackResult]]:
    """Optional: results from a real-model run, if the user saved one (attack_results.anthropic.json)."""
    f = out / "attack_results.anthropic.json"
    if not f.exists():
        return {}
    by_family: dict[int, list[AttackResult]] = {}
    for r in (AttackResult(**x) for x in json.loads(f.read_text())):
        by_family.setdefault(r.check_family, []).append(r)
    return by_family


def _has_harness(target_dir: Path) -> bool:
    """A dynamic worst-case run needs the attack harness wired for THIS target."""
    return target_dir.resolve() == sandbox.TARGET.resolve()


def build_report(target_dir: str | Path, dynamic: bool | None = None) -> dict:
    target_dir = Path(target_dir)
    out = Path("runs") / target_dir.name
    findings = [Finding(**f) for f in json.loads((out / "findings.json").read_text())]
    controls = loader.controls()
    names = loader.ids()
    if dynamic is None:
        dynamic = _has_harness(target_dir)                    # auto: only the bundled target has a harness
    worst = _worst_case(target_dir) if dynamic else {}
    current = _current_model(out) if dynamic else {}

    weaknesses = []
    for fam in sorted({f.check_family for f in findings}):
        fam_findings = [f for f in findings if f.check_family == fam]
        control = controls[fam]
        worst_hits = [r for r in worst.get(fam, []) if r.success]
        cur = current.get(fam)
        weaknesses.append({
            "family": fam,
            "name": loader.families()[fam]["name"],
            "missing_control": control["control"],
            "why_model_independent": " ".join(control["rationale"].split()),
            "code_fix": control["code_fix"],
            "severity": min((f.severity for f in fam_findings), key=lambda s: SEV_RANK[s]),
            "locations": [{"id": f.id, "file": f.file, "line": f.line, "rule": f.rule_id} for f in fam_findings],
            "owasp": control["owasp"],
            "atlas": [f"{a} {names.get(a, '')}".strip() for a in control["atlas"]],
            "worst_case_exploitable": bool(worst_hits) if dynamic else None,   # None = not dynamically tested
            "worst_case_evidence": [r.reason for r in worst_hits[:2]],
            "current_model_resisted": (cur is not None and not any(r.success for r in cur)),
            "status": "open",
        })
    weaknesses.sort(key=lambda w: (not bool(w["worst_case_exploitable"]), SEV_RANK[w["severity"]]))

    report = {
        "target": str(target_dir),
        "summary": {
            "structural_weaknesses": len(weaknesses),
            "dynamically_tested": dynamic,
            "worst_case_exploitable": sum(1 for w in weaknesses if w["worst_case_exploitable"]),
            "current_model_tested": bool(current),
            "current_model_resisted_all": bool(current) and all(w["current_model_resisted"] for w in weaknesses),
        },
        "weaknesses": weaknesses,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    (out / "structural_report.md").write_text(to_markdown(report))
    return report


def to_markdown(report: dict) -> str:
    s = report["summary"]
    if not s.get("dynamically_tested", True):
        head = (f"# Structural weakness report: {report['target']}\n\n"
                f"**{s['structural_weaknesses']} structural weaknesses** (missing code/design guardrails), "
                "found by static analysis. No attack harness is wired for this target, so worst-case "
                "exploitability was not run - but each weakness is a code/design gap that holds for any model.\n\n"
                "| Severity | Weakness | Missing control | OWASP | Where |\n| --- | --- | --- | --- | --- |")
        rows = [f"| {w['severity']} | {w['name']} | {w['missing_control']} | {', '.join(w['owasp'])} | "
                + ", ".join(f"{l['file']}:{l['line']}" for l in w['locations']) + " |" for w in report["weaknesses"]]
        details = []
        for w in report["weaknesses"]:
            details += [f"## {w['name']} (family {w['family']}, {w['severity']})",
                        f"**Missing control:** {w['missing_control']}",
                        f"**Why this is model-independent:** {w['why_model_independent']}",
                        f"**Code fix:** {w['code_fix']}",
                        f"**Locations:** " + ", ".join(f"{l['file']}:{l['line']} ({l['rule']})" for l in w["locations"]), ""]
        return "\n".join([head, *rows, "", *details])
    note = ""
    if s["current_model_tested"]:
        verb = "resisted all attacks" if s["current_model_resisted_all"] else "was exploited on some attacks"
        note = (f"\n\nThe current model {verb} in a live run. Model resistance is **not** a fix: "
                "the code weaknesses below remain, and a weaker or future model could be exploited.")
    lines = [
        f"# Structural weakness report: {report['target']}",
        "",
        f"**{s['structural_weaknesses']} structural weaknesses** (missing code/design guardrails). "
        f"**{s['worst_case_exploitable']}** are exploitable by a deliberately weak model, so the risk "
        f"does not depend on the strength of the model in production.{note}",
        "",
        "Each weakness is a guardrail the application must implement itself. Fixing the listed control "
        "closes it for every model, strong or weak.",
        "",
        "| Severity | Weakness | Missing control | Worst-case (weak model) | Current model | OWASP | Where |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for w in report["weaknesses"]:
        worst = "EXPLOITED" if w["worst_case_exploitable"] else "not shown"
        cur = "resisted" if w["current_model_resisted"] else ("-" if not report["summary"]["current_model_tested"] else "exploited")
        where = ", ".join(f"{l['file']}:{l['line']}" for l in w["locations"])
        lines.append(f"| {w['severity']} | {w['name']} | {w['missing_control']} | {worst} | {cur} "
                     f"| {', '.join(w['owasp'])} | {where} |")
    lines.append("")
    for w in report["weaknesses"]:
        lines += [f"## {w['name']} (family {w['family']}, {w['severity']})",
                  f"**Missing control:** {w['missing_control']}",
                  f"**Why this is model-independent:** {w['why_model_independent']}",
                  f"**Code fix:** {w['code_fix']}",
                  f"**ATLAS:** {', '.join(w['atlas'])}",
                  f"**Locations:** " + ", ".join(f"{l['file']}:{l['line']} ({l['rule']})" for l in w["locations"]),
                  ""]
    return "\n".join(lines)
