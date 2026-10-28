"""scripts/agent_passrate_summary.py on two hand-made runs: one clean, one with every kind of slip it looks for."""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_passrate_summary as aps  # noqa: E402

CASE_1 = """# Evidence bundle: case_001

## [A1] Video
- E1.1 (info) No interview recording in the case folder, so the video checks did not run.

## [A3] Application
- E3.1 (weak, 1 pt) Candidate name is 100% similar to the persona name on watchlist row W-0002 (attribution: Medium).
"""
CASE_2 = """# Evidence bundle: case_002

## [A3] Application
- E3.1 (strong, 4 pts) Email jose.watson3509@example.org matches watchlist row W-0117 (highest attribution: High), part of ring R-006 with 5 personas.
"""
BUNDLE_BAD = """BUNDLE CHECK (code)

BUNDLE PROBLEMS / COVERAGE GAPS
- The Orchestrator's notes name IDs that are not in the bundle: E1.2.
"""
BUNDLE_OK = "BUNDLE CHECK (code)\n\nBUNDLE PROBLEMS / COVERAGE GAPS\n- none\n"
EVIDENCE_BAD = """EVIDENCE CHECK (code)

- Evidence citations in report: 2; verified: 0

EVIDENCE PROBLEMS
- E3.1 [A3]: quote does not appear verbatim in that evidence line.
- E3.1 [A3]: quote does not appear verbatim in that evidence line.
- Scored evidence left out of the report: E3.2 (moderate, 2 pts).

Note: this proves quotes are real and correctly tagged. It does not prove the sentences are right.
"""
EVIDENCE_OK = "EVIDENCE CHECK (code)\n\nEVIDENCE PROBLEMS\n- none\n\nNote: ...\n"
REPORT_BAD = """## [A3] Application
- A name match.
  Evidence: E3.1 "candidate name is 100% similar" [A3]
- A watchlist email.
  Evidence: E3.1 "jose.watson3509@example.org matches watchlist row W-0117" [A3]

## Contradictions
- None found. The video and the application point the same way (E1.1; E3.1).
"""
REPORT_OK = '## [A3] Application\n- Email match.\n  Evidence: E3.1 "matches watchlist row W-0117" [A3]\n'


def make_runs(tmp_path):
    out, runs, prompts = tmp_path / "out", tmp_path / "runs", tmp_path / "prompts"
    for case, text in (("case_001", CASE_1), ("case_002", CASE_2)):
        (out / case).mkdir(parents=True)
        (out / case / "evidence.md").write_text(text, encoding="utf-8")
    runs.mkdir()
    prompts.mkdir()
    (prompts / "orchestrator.md").write_text('for example: "None found. (E1.2; E3.1)."', encoding="utf-8")
    files = {"r1_case_001": (BUNDLE_BAD, EVIDENCE_BAD, REPORT_BAD), "r1_case_002": (BUNDLE_OK, EVIDENCE_OK, REPORT_OK)}
    for stem, (bundle, evidence, report) in files.items():
        (runs / f"{stem}_bundle_check.txt").write_text(bundle, encoding="utf-8-sig")    # PowerShell writes a BOM
        (runs / f"{stem}_evidence_check.txt").write_text(evidence, encoding="utf-8-sig")
        (runs / f"{stem}_report.md").write_text(report, encoding="utf-8-sig")
    (tmp_path / "rate.csv").write_text("round,case,status,seconds\n1,case_001,done,12\n1,case_002,done,9\n",
                                       encoding="utf-8-sig")
    return ["--runs", str(runs), "--out", str(out), "--prompts", str(prompts), "--csv", str(tmp_path / "rate.csv")]


def test_failures_get_a_kind_and_quotes_get_an_origin(tmp_path, capsys):
    args = make_runs(tmp_path)
    runs = tmp_path / "runs"
    results = aps.main(args)
    printed = capsys.readouterr().out
    assert "runs: 2; both checks passed: 1 (50%)" in printed and "median 10" in printed
    bad = next(r for r in results if r["case"] == "case_001")
    kinds = [(row["kind"], row["detail"]) for row in bad["rows"]]
    assert ("names an ID not in the bundle",
            "The Orchestrator's notes name IDs that are not in the bundle: E1.2. (the prompts use it as an example)") in kinds
    origins = sorted(d.rsplit(": ", 1)[-1] for k, d in kinds if k == "quote not verbatim")
    assert origins == ["capital letters only", "from another case's bundle (case_002)"]
    foreign = {d for k, d in kinds if k == "from another case"}
    assert {"jose.watson3509@example.org (case_002)", "W-0117 (case_002)"} <= foreign
    assert any(k == "same-way sentence cites an info line" and d.startswith("E1.1:") for k, d in kinds)
    assert any(k == "scored evidence left out of the report" for k, _ in kinds)
    assert next(r for r in results if r["case"] == "case_002")["rows"] == []
    rows = list(csv.DictReader(open(runs / "problems.csv", encoding="utf-8")))
    assert len(rows) == len(bad["rows"]) and {r["case"] for r in rows} == {"case_001"}


def test_recheck_runs_the_current_checks_on_the_saved_texts(tmp_path, capsys):
    args = make_runs(tmp_path)
    results = aps.main(args + ["--recheck"])
    printed = capsys.readouterr().out
    assert "Bundle Check on 0 of 2 runs" in printed
    bad = next(r for r in results if r["case"] == "case_001")
    same_way = [row for row in bad["rows"] if row["kind"] == "same-way sentence cites an info line"]
    assert [row["check"] for row in same_way] == ["evidence"]           # the check flags it now; the scan stays quiet
    assert not any(row["kind"] == "scored evidence left out of the report" for row in bad["rows"])   # E3.1 is cited
    assert (tmp_path / "runs" / "problems_recheck.csv").exists()


def test_agent_passrate_script_runs_the_flow_and_grades_each_run(tmp_path, monkeypatch, capsys):
    """scripts/agent_passrate.py with the flow swapped for a function that returns a faithful committee text."""
    import agent_passrate as ap_script
    from chimera.agents_client import mock_flow
    import json

    evidence_dir = tmp_path / "out_heldout"
    for case in ("case_101", "case_102"):
        src = Path(__file__).resolve().parents[1] / "out" / ("case_001" if case == "case_101" else "case_002")
        if not (src / "evidence.json").exists():
            import pytest
            pytest.skip("needs out/case_001 and out/case_002 from a pipeline run")
        (evidence_dir / case).mkdir(parents=True)
        for name in ("evidence.md", "evidence.json"):
            text = (src / name).read_text(encoding="utf-8").replace(src.name, case)
            (evidence_dir / case / name).write_text(text, encoding="utf-8")

    def fake_flow(settings, case_id, log=print):
        ev = json.loads((evidence_dir / case_id / "evidence.json").read_text(encoding="utf-8"))
        return {**mock_flow(ev), "mode": "langflow", "session_id": f"chimera-{case_id}-test"}

    monkeypatch.setattr(ap_script.agents_client, "run_flow", fake_flow)
    monkeypatch.setattr(ap_script.agents_client, "flow_configured", lambda s: True)
    monkeypatch.setattr(ap_script, "ROOT", tmp_path)
    monkeypatch.setenv("LANGFLOW_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("LANGFLOW_FLOW_ID", "x")
    monkeypatch.setenv("LANGFLOW_API_KEY", "x")
    staged = tmp_path / "out"
    ap_script.main(["--evidence-dir", str(evidence_dir), "--stage-into", str(staged), "--name", "t", "--rounds", "2",
                    "--quiet"])
    printed = capsys.readouterr().out
    assert "runs: 4; both checks passed: 4 (100%)" in printed
    assert (staged / "case_101" / "evidence.md").read_text(encoding="utf-8") == \
        (evidence_dir / "case_101" / "evidence.md").read_text(encoding="utf-8")
    keep = tmp_path / "data" / "scores" / "agent_passrate_t"
    assert sorted(p.name for p in keep.glob("r2_case_102_*")) == \
        ["r2_case_102_analysts.txt", "r2_case_102_bundle_check.txt", "r2_case_102_evidence_check.txt", "r2_case_102_report.md"]
    rows = list(csv.DictReader(open(tmp_path / "data" / "scores" / "agent_passrate_t.csv", encoding="utf-8")))
    assert len(rows) == 4 and rows[0]["session_id"] == "chimera-case_101-test" and rows[0]["status"] == "done"
