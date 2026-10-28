"""LLM remediation agent: real faulty code -> anchored fix -> non-destructive validation.

The LLM is faked. We assert the agent validates anchors against the REAL file, compiles the
patched result, renders a diff, and NEVER modifies the target.
"""
import json

from sentinel import llm
from sentinel.agents import remediate
from sentinel.models import Finding
from conftest import TARGET


def _finding(**kw):
    base = dict(id="R1", check_family=3, title="send_email has no allow-list",
                file="app/tools.py", line=37, owasp=["LLM03"], atlas=["AML.T0053"],
                evidence="no recipient allow-list", severity="high", status="confirmed")
    base.update(kw)
    return Finding(**base)


def _fake_fix(monkeypatch, edits, **fields):
    """Make llm.ask_json return a fixed _LlmFix regardless of prompt."""
    def fake(prompt, schema, budget, max_out=800):
        budget.used += 10
        data = dict(diagnosis="User-controlled recipient reaches a side-effecting tool.",
                    fix_summary="Add a recipient allow-list in code.",
                    edits=edits, rationale="The code refuses, so no model has to.",
                    verification=["Re-run autoprobe; the email probe no longer sends externally.",
                                  "Re-run analyze; the f3 rule no longer fires."],
                    confidence="high", risk_notes="")
        data.update(fields)
        return schema(**data)
    monkeypatch.setattr(llm, "ask_json", fake)
    monkeypatch.setattr(remediate.llm, "enabled", lambda: True)


def test_valid_anchor_produces_a_compiling_patch(tmp_path, monkeypatch):
    # A real anchor copied from HelpDeskBot's tools.py.
    real = (TARGET / "app/tools.py").read_text()
    anchor = 'def send_email(to: str, subject: str, body: str) -> str:'
    assert anchor in real                                   # sanity: the anchor is real
    _fake_fix(monkeypatch, edits=[{
        "old": anchor,
        "new": anchor + '\n    if not to.endswith("@acme.test"):\n        return "Blocked: external recipient."'}])
    (tmp_path / "findings.json").write_text(json.dumps([_finding().model_dump()]))

    rep = remediate.remediate(TARGET, tmp_path)
    r = rep["remediations"][0]
    assert r["applies"] is True and r["compiles"] is True
    assert r["patch"].startswith("--- a/app/tools.py")
    assert "allow-list" in r["fix_summary"].lower()
    assert r["verification"]                                 # steps present
    # the report + patch file were written
    assert (tmp_path / "remediation.md").exists()
    assert (tmp_path / "suggested_fixes" / "R1.patch").exists()
    # the TARGET source was NOT modified
    assert (TARGET / "app/tools.py").read_text() == real


def test_missing_anchor_is_flagged_not_trusted(tmp_path, monkeypatch):
    _fake_fix(monkeypatch, edits=[{"old": "this text is not in the file at all", "new": "x"}])
    (tmp_path / "findings.json").write_text(json.dumps([_finding().model_dump()]))
    rep = remediate.remediate(TARGET, tmp_path)
    r = rep["remediations"][0]
    assert r["applies"] is False
    assert r["confidence"] == "low"
    assert any("anchor not found" in p for p in r["problems"])


def test_broken_patch_is_caught_by_compile_check(tmp_path, monkeypatch):
    anchor = 'def send_email(to: str, subject: str, body: str) -> str:'
    _fake_fix(monkeypatch, edits=[{"old": anchor, "new": "def send_email(  # broken syntax ("}])
    (tmp_path / "findings.json").write_text(json.dumps([_finding().model_dump()]))
    rep = remediate.remediate(TARGET, tmp_path)
    r = rep["remediations"][0]
    assert r["compiles"] is False and r["confidence"] == "low"
    assert any("does not compile" in p for p in r["problems"])


def test_selection_prefers_confirmed_and_severe(tmp_path):
    findings = [
        _finding(id="A", status="suspected", severity="low"),      # dropped
        _finding(id="B", status="suspected", severity="high"),     # kept
        _finding(id="C", status="confirmed", severity="medium"),   # kept, first
    ]
    chosen = remediate.select_findings(findings)
    ids = [f.id for f in chosen]
    assert "A" not in ids
    assert ids[0] == "C"                                    # confirmed ranks first
    assert set(ids) == {"B", "C"}
