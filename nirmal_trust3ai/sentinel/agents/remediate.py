"""Agent 5 - Remediate (LLM-driven, suggest-only).

This agent works on ANY codebase: for each real finding it reads the actual faulty source, asks a
real model to propose a concrete fix anchored to the family's model-independent control, validates
that fix WITHOUT touching the target, and writes a remediation report plus a ready-to-apply patch
per finding. There is no hardcoded, per-app fix table - the fix is derived from the real code.

It never modifies the target. You review the suggestions and apply them yourself.

How a suggestion is kept trustworthy:
  1. The model returns ANCHORED edits (exact `old` snippet copied from the shown code -> `new`),
     not a free-form diff. We can then check each anchor really exists in the file.
  2. We apply the edits to an IN-MEMORY copy and, for Python, compile-check the result.
  3. We render the unified diff ourselves with difflib, so the report and the .patch are faithful.
A fix whose anchor is missing, ambiguous, or whose result doesn't compile is reported with a clear
warning and low confidence instead of being silently trusted.
"""
from __future__ import annotations

import difflib
import json
import os
import py_compile
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from sentinel import llm
from sentinel.kb import loader
from sentinel.models import Finding

CONTEXT_LINES = 12          # lines of code shown around a finding
MAX_FIXES = 12              # bound the LLM spend per run
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class _Edit(BaseModel):
    old: str = Field(description="Exact snippet copied verbatim from the shown code")
    new: str = Field(description="Replacement for `old` (may be multi-line); empty string deletes it")


class _LlmFix(BaseModel):
    """What the model proposes for one finding."""
    diagnosis: str = Field(description="What is wrong, in one or two sentences, tied to the control")
    fix_summary: str = Field(description="What to change, in one line")
    edits: list[_Edit] = Field(default_factory=list,
                               description="Anchored edits that implement the fix on THIS file")
    rationale: str = Field(description="Why this holds regardless of how strong or weak the model is")
    verification: list[str] = Field(default_factory=list,
                                    description="Ordered, concrete steps to confirm the fix works")
    confidence: str = Field(default="medium", description="low | medium | high")
    risk_notes: str = Field(default="", description="What to double-check before applying (callers, etc.)")


class Remediation(BaseModel):
    """One finding's suggested fix, with the result of non-destructive validation."""
    finding_id: str
    title: str
    file: str
    line: int
    family: int
    owasp: list[str] = Field(default_factory=list)
    atlas: list[str] = Field(default_factory=list)
    severity: str = "medium"
    status: str = "suspected"
    diagnosis: str = ""
    fix_summary: str = ""
    rationale: str = ""
    verification: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    risk_notes: str = ""
    patch: str = ""                 # unified diff we rendered (empty if no valid edits)
    applies: bool = False           # every anchor found + applied cleanly
    compiles: bool = True           # patched Python still compiles (True for non-Python)
    problems: list[str] = Field(default_factory=list)


def select_findings(findings: list[Finding], cap: int = MAX_FIXES) -> list[Finding]:
    """Confirmed weaknesses first, then high/critical static ones; capped for token budget."""
    eligible = [f for f in findings if f.status == "confirmed" or f.severity in ("high", "critical")]

    def rank(f: Finding):
        confirmed_first = 0 if f.status == "confirmed" else 1
        return (confirmed_first, SEVERITY_RANK.get(f.severity, 2), f.file, f.line)

    return sorted(eligible, key=rank)[:cap]


def _window(target_dir: Path, finding: Finding) -> tuple[str, str]:
    """Return (raw code window, note). The window is raw (no line prefixes) so anchors match."""
    path = target_dir / finding.file
    if not path.exists():
        return "", f"source file not found: {finding.file}"
    lines = path.read_text(errors="ignore").splitlines()
    start = max(0, finding.line - 1 - CONTEXT_LINES)
    end = min(len(lines), (finding.end_line or finding.line) + CONTEXT_LINES)
    window = "\n".join(lines[start:end])
    return window, f"lines {start + 1}-{end} of {finding.file}"


def _build_prompt(finding: Finding, window: str, note: str) -> str:
    fam = loader.families().get(finding.check_family, {})
    control = loader.controls().get(finding.check_family, {})
    return (
        "Fix one security weakness in the code below. Propose the SMALLEST change that removes the "
        "weakness by adding a structural control - a guardrail in the code, not a plea for the model "
        "to behave.\n\n"
        f"Weakness: {finding.title}\n"
        f"Family: {finding.check_family} - {fam.get('name', '')}  (OWASP {', '.join(finding.owasp)}; "
        f"ATLAS {', '.join(finding.atlas)})\n"
        f"Evidence: {finding.evidence[:500]}\n\n"
        f"The model-independent control for this family:\n"
        f"  {control.get('control', '')}\n"
        f"  Why: {control.get('rationale', '').strip()}\n"
        f"  How: {control.get('code_fix', '')}\n\n"
        f"The code to fix ({note}):\n"
        f"{llm.wrap_untrusted(window)}\n\n"
        "Return JSON matching the schema. For `edits`, each `old` MUST be copied verbatim from the "
        "code above and be unique within it; `new` is its replacement. If the fix truly cannot be "
        "expressed as edits to this snippet, return an empty `edits` list and describe it in "
        "`fix_summary`. `verification` must be concrete steps to confirm the weakness is gone "
        "(e.g. the probe to re-run, the test to add, what to re-scan)."
    )


def _apply(content: str, edits: list[_Edit]) -> tuple[str, list[str]]:
    """Apply anchored edits to an in-memory copy. Returns (patched, problems)."""
    patched, problems = content, []
    for e in edits:
        count = patched.count(e.old)
        if count == 1:
            patched = patched.replace(e.old, e.new, 1)
        elif count == 0:
            problems.append(f"anchor not found in file: {e.old[:50]!r}")
        else:
            problems.append(f"anchor is not unique ({count}x), skipped: {e.old[:50]!r}")
    return patched, problems


def _compiles(rel_path: str, content: str) -> tuple[bool, str]:
    """Compile-check the patched content for Python files; a no-op (True) otherwise."""
    if not rel_path.endswith(".py"):
        return True, ""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(content)
        tmp = fh.name
    try:
        py_compile.compile(tmp, doraise=True)
        return True, ""
    except py_compile.PyCompileError as e:
        return False, str(e).splitlines()[-1][:200]
    finally:
        os.unlink(tmp)


def _remediate_one(target_dir: Path, finding: Finding, budget: llm.Budget) -> Remediation:
    base = Remediation(finding_id=finding.id, title=finding.title, file=finding.file, line=finding.line,
                       family=finding.check_family, owasp=finding.owasp, atlas=finding.atlas,
                       severity=finding.severity, status=finding.status)
    window, note = _window(target_dir, finding)
    if not window:
        base.problems = [note]
        return base

    fix = llm.ask_json(_build_prompt(finding, window, note), _LlmFix, budget, max_out=1200)
    if fix is None:
        base.problems = ["LLM returned no proposal (disabled or budget exhausted)"]
        return base

    base.diagnosis, base.fix_summary, base.rationale = fix.diagnosis, fix.fix_summary, fix.rationale
    base.verification, base.confidence, base.risk_notes = fix.verification, fix.confidence, fix.risk_notes

    if not fix.edits:                                   # described-only fix (no mechanical patch)
        base.problems = ["model gave no anchored edits - described fix only; apply by hand"]
        return base

    original = (target_dir / finding.file).read_text(errors="ignore")
    patched, problems = _apply(original, fix.edits)
    base.problems = problems
    base.applies = not problems and patched != original
    if base.applies:
        ok, detail = _compiles(finding.file, patched)
        base.compiles = ok
        if not ok:
            base.problems.append(f"patched file does not compile: {detail}")
        base.patch = "".join(difflib.unified_diff(
            original.splitlines(keepends=True), patched.splitlines(keepends=True),
            fromfile=f"a/{finding.file}", tofile=f"b/{finding.file}"))
    if base.applies and base.compiles:
        base.confidence = base.confidence or "medium"
    else:                                               # downgrade: don't oversell a shaky fix
        base.confidence = "low"
    return base


def remediate(target_dir: str | Path, out_dir: str | Path, budget: llm.Budget | None = None) -> dict:
    """Suggest a fix for each selected finding; write a report + patches. Never touches the target."""
    target_dir, out_dir = Path(target_dir), Path(out_dir)
    budget = budget or llm.Budget(40_000)
    findings = [Finding(**f) for f in json.loads((out_dir / "findings.json").read_text())]
    chosen = select_findings(findings)

    results = [_remediate_one(target_dir, f, budget) for f in chosen]

    patch_dir = out_dir / "suggested_fixes"
    for r in results:
        if r.patch:
            patch_dir.mkdir(exist_ok=True)
            (patch_dir / f"{r.finding_id}.patch").write_text(r.patch)

    (out_dir / "remediation.json").write_text(json.dumps([r.model_dump() for r in results], indent=2))
    (out_dir / "remediation.md").write_text(_to_markdown(target_dir, results))

    summary = {
        "selected": len(results),
        "with_patch": sum(1 for r in results if r.patch and r.compiles),
        "described_only": sum(1 for r in results if not r.patch),
        "needs_review": sum(1 for r in results if r.problems),
    }
    return {"target": str(target_dir), "summary": summary, "remediations": [r.model_dump() for r in results]}


def _to_markdown(target_dir: Path, results: list[Remediation]) -> str:
    out = ["# Remediation suggestions",
           "",
           f"Target: `{target_dir.name}`  ·  {len(results)} finding(s) addressed.",
           "",
           "> These are **suggestions**. Nothing in the target was modified. Review each patch, then "
           "apply it yourself (e.g. `git apply runs/<app>/suggested_fixes/<id>.patch`) and run the "
           "verification steps.",
           ""]
    for r in results:
        out.append(f"## {r.finding_id} · {r.title}")
        out.append("")
        out.append(f"- **Location:** `{r.file}:{r.line}`")
        out.append(f"- **Family {r.family}** · OWASP {', '.join(r.owasp) or '-'} · ATLAS {', '.join(r.atlas) or '-'}")
        out.append(f"- **Severity:** {r.severity}  ·  **Status:** {r.status}  ·  **Confidence:** {r.confidence}")
        out.append("")
        if r.diagnosis:
            out.append(f"**Diagnosis.** {r.diagnosis}")
            out.append("")
        if r.fix_summary:
            out.append(f"**Fix.** {r.fix_summary}")
            out.append("")
        if r.patch:
            status = "applies cleanly" + ("" if r.compiles else " — but does NOT compile, review carefully")
            out.append(f"_Suggested patch ({status}):_")
            out.append("")
            out.append("```diff")
            out.append(r.patch.rstrip())
            out.append("```")
            out.append("")
        if r.rationale:
            out.append(f"**Why it holds (model-independent).** {r.rationale}")
            out.append("")
        if r.verification:
            out.append("**Verify:**")
            out.append("")
            for i, step in enumerate(r.verification, 1):
                out.append(f"{i}. {step}")
            out.append("")
        if r.risk_notes:
            out.append(f"**Before applying:** {r.risk_notes}")
            out.append("")
        if r.problems:
            out.append("**⚠ Needs review:** " + "; ".join(r.problems))
            out.append("")
        out.append("---")
        out.append("")
    return "\n".join(out)
