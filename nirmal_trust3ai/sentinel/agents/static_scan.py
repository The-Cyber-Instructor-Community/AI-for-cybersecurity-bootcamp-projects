"""Agent 2 - Static Scan. Runs Sentinel's Semgrep rules, then (optionally) asks an LLM to triage each hit.

Step 1 (free): Semgrep with sentinel/checks/rules/*.yaml, run locally with metrics off.
Step 2 (free): each hit becomes a Finding. OWASP/ATLAS tags come from families.yaml,
               so a rule never has to repeat them.
Step 3 (optional LLM): per hit, send ~20 lines of code (not the whole file), wrapped
               as untrusted, and ask "true positive? how severe? why?". False positives are dropped.
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from sentinel import llm
from sentinel.kb import loader
from sentinel.models import Finding

RULES = Path(__file__).resolve().parent.parent / "checks" / "rules"
SEVERITY = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}


def run_semgrep(target_dir: str | Path) -> list[dict]:
    cmd = ["semgrep", "scan", "--config", str(RULES), "--json", "--quiet", "--metrics=off",
           "--disable-version-check", "--exclude", "tests", "--exclude", "sandbox", "."]
    out = subprocess.run(cmd, cwd=target_dir, capture_output=True, text=True, check=False)
    data = json.loads(out.stdout or "{}")
    if data.get("errors"):
        raise RuntimeError(f"Semgrep errors: {data['errors']}")
    return data.get("results", [])


def snippet(target_dir: Path, file: str, start: int, end: int, context: int = 10) -> str:
    lines = (target_dir / file).read_text().splitlines()
    lo, hi = max(0, start - 1 - context), min(len(lines), end + context)
    return "\n".join(f"{i + 1:4} {lines[i]}" for i in range(lo, hi))


def enclosing_function(target_dir: Path, file: str, line: int) -> str | None:
    """Name of the function that contains `line` (used as the finding's tool name)."""
    tree = ast.parse((target_dir / file).read_text())
    inside = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.lineno <= line <= n.end_lineno]
    return min(inside, key=lambda n: n.end_lineno - n.lineno).name if inside else None


def to_findings(results: list[dict], target_dir: Path) -> list[Finding]:
    fams = loader.families()
    findings = []
    seen = set()
    for i, r in enumerate(results, 1):
        key = (r["check_id"].split(".")[-1], r["path"], r["start"]["line"], r["end"]["line"])
        if key in seen:                              # Semgrep can report one spot twice; keep it once
            continue
        seen.add(key)
        family = int(r["extra"]["metadata"]["family"])
        file = r["path"].removeprefix("./")
        tool = enclosing_function(target_dir, file, r["start"]["line"])
        findings.append(Finding(
            id=f"S{i:02d}", check_family=family, title=r["extra"]["message"], rule_id=r["check_id"].split(".")[-1],
            owasp=fams[family]["owasp"], atlas=fams[family]["atlas"], file=file,
            line=r["start"]["line"], end_line=r["end"]["line"], tool=tool,
            evidence=snippet(target_dir, file, r["start"]["line"], r["end"]["line"], context=0),
            severity=SEVERITY.get(r["extra"]["severity"], "medium"),
        ))
    return findings


class Verdict(BaseModel):
    true_positive: bool
    severity: Literal["low", "medium", "high", "critical"]
    explanation: str


def triage(findings: list[Finding], target_dir: Path, budget: llm.Budget) -> list[Finding]:
    """Optional LLM pass. Without an LLM every hit is kept as-is."""
    kept, triaged = [], 0
    for f in findings:
        if f.severity not in ("high", "critical") or triaged >= MAX_TRIAGE:
            kept.append(f)                           # skip low-value / over-cap findings (keep as-is)
            continue
        triaged += 1
        code = snippet(target_dir, f.file, f.line, f.end_line or f.line)
        prompt = (f"A rule flagged this code for: {f.title}\nCheck family: {loader.families()[f.check_family]['name']}\n"
                  f"File {f.file}, lines {f.line}-{f.end_line}.\n{llm.wrap_untrusted(code)}\n"
                  "Is this a true positive? Give severity and a one-sentence explanation a developer will understand.")
        verdict = llm.ask_json(prompt, Verdict, budget, max_out=300)
        # Self-robustness: triage NEVER drops a finding. If the reviewed code tries to injection the
        # triage step into saying "false positive", the finding is kept and merely marked "disputed".
        if verdict is None:                                   # LLM off, over budget or bad reply
            kept.append(f)
        elif verdict.true_positive:
            kept.append(f.model_copy(update={"triage": "confirmed", "severity": verdict.severity, "title": verdict.explanation}))
        else:
            kept.append(f.model_copy(update={"triage": "disputed"}))
    return kept


# Rules that only make sense for a real agent TOOL (not any similarly-named function).
TOOL_SCOPED_RULES = {"f3-side-effect-tool-without-guard"}
MAX_TRIAGE = 40                                     # bound LLM cost on big repos


def run_rules(target_dir: Path) -> list[Finding]:
    return to_findings(run_semgrep(target_dir), target_dir)


def filter_by_map(findings: list[Finding], system_map) -> list[Finding]:
    """Drop tool-scoped findings whose function is not actually a recon-identified agent tool.

    This removes the biggest real-repo false-positive source: ordinary methods named send_*/delete_*
    that are not exposed to the model. If recon found no tools, the scoped rules are dropped too
    (they would otherwise be noise); the LLM-recon pass can still surface genuine tools it finds.
    """
    tools = {t.name for t in system_map.tools}
    kept = []
    for f in findings:
        if f.rule_id in TOOL_SCOPED_RULES and f.tool not in tools:
            continue
        kept.append(f)
    return kept


def scan(target_dir: str | Path, budget: llm.Budget | None = None, system_map=None) -> list[Finding]:
    target_dir = Path(target_dir)
    findings = run_rules(target_dir)
    if system_map is not None:
        findings = filter_by_map(findings, system_map)
    if budget and llm.enabled():
        findings = triage(findings, target_dir, budget)
    return findings
