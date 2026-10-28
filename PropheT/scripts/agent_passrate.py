"""Send cases through the LangFlow flow straight from Python and grade every run with the code checks.

The same measurement as tools\\agent_passrate.ps1 on the PC, without the Console in the loop: for each round and
case, run_flow (a fresh LangFlow session per run), then Bundle Check on the analysts' text and Evidence Check on
the report, both computed here from <evidence-dir>/<case>/evidence.md. Every run's analysts' text, report and
check texts are kept in data/scores/agent_passrate_<name>/, with a CSV row per run, so
scripts/agent_passrate_summary.py can sort the failures afterwards.

The LangFlow components read evidence from the repo's out/ folder, so a held-out batch scored elsewhere is staged:
--stage-into copies each case's evidence.md and evidence.json there before the run (and leaves them).

Held-out batch (synthetic; the prompts were tuned on cases/, so a batch from another seed is the honest number):
    python synth/make_synthetic.py --seed 2026 --first 101 --cases cases_heldout --data data_heldout
    python -m chimera run --cases cases_heldout --watchlist data_heldout/watchlist_synthetic.csv --out out_heldout
    python scripts/agent_passrate.py --evidence-dir out_heldout --stage-into out --name heldout_seed2026
LangFlow (and Ollama) must be running; LANGFLOW_URL, LANGFLOW_FLOW_ID and LANGFLOW_API_KEY come from .env.
"""
import argparse
import csv
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from chimera import agents_client  # noqa: E402
from chimera.api import Settings  # noqa: E402
from chimera.checks import bundle_check, evidence_check  # noqa: E402

FIELDS = ["round", "case", "status", "seconds", "bundle_problems", "evidence_problems", "mode", "session_id"]


def stage(evidence_dir: Path, case: str, into: Path) -> None:
    """Put the case's evidence where the LangFlow components look for it (unchanged if already the same)."""
    for name in ("evidence.md", "evidence.json"):
        src, dst = evidence_dir / case / name, into / case / name
        if src.exists() and (not dst.exists() or dst.read_bytes() != src.read_bytes()):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)


def run_case(settings, case: str, evidence_md: str, keep: Path, rnd: int, log) -> dict:
    t0 = time.time()
    row = {"round": rnd, "case": case, "status": "done", "seconds": 0, "bundle_problems": "", "evidence_problems": "",
           "mode": "langflow", "session_id": ""}
    try:
        result = agents_client.run_flow(settings, case, log=log)
        analysts, report = result.get("analysts", ""), result.get("report", "")
        bundle = bundle_check(evidence_md, analysts) if analysts else "BUNDLE CHECK (code)\n\n- no analysts' text was returned"
        evid = evidence_check(evidence_md, report) if report else "EVIDENCE CHECK (code)\n\n- no report was returned"
        for name, text in (("analysts.txt", analysts), ("report.md", report), ("bundle_check.txt", bundle),
                           ("evidence_check.txt", evid)):
            (keep / f"r{rnd}_{case}_{name}").write_text(text, encoding="utf-8")
        row.update(bundle_problems="- none" not in bundle, evidence_problems="- none" not in evid,
                   session_id=result.get("session_id", ""))
    except Exception as e:                                    # noqa: BLE001 - one failed run must not stop the batch
        row.update(status="error", mode=str(e).replace(",", ";")[:120])
    row["seconds"] = round(time.time() - t0)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--evidence-dir", type=Path, default=ROOT / "out", help="folder with <case>/evidence.md")
    ap.add_argument("--stage-into", type=Path, default=None, help="copy evidence into this out/ folder first")
    ap.add_argument("--cases", nargs="*", default=None, help="case IDs (default: every case_* in --evidence-dir)")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--name", required=True, help="data/scores/agent_passrate_<name>")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    settings = Settings.from_env()
    if not agents_client.flow_configured(settings):
        sys.exit("LangFlow is not configured (LANGFLOW_URL, LANGFLOW_FLOW_ID, LANGFLOW_API_KEY in .env)")
    cases = args.cases or sorted(p.parent.name for p in args.evidence_dir.glob("case_*/evidence.md"))
    if not cases:
        sys.exit(f"no case_*/evidence.md under {args.evidence_dir}")
    keep = ROOT / "data" / "scores" / f"agent_passrate_{args.name}"
    keep.mkdir(parents=True, exist_ok=True)
    csv_path = ROOT / "data" / "scores" / f"agent_passrate_{args.name}.csv"
    log = (lambda m: None) if args.quiet else print

    evidence = {c: (args.evidence_dir / c / "evidence.md").read_text(encoding="utf-8") for c in cases}
    if args.stage_into:
        for c in cases:
            stage(args.evidence_dir, c, args.stage_into)
    print(f"{len(cases)} cases x {args.rounds} rounds -> {keep}")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for rnd in range(1, args.rounds + 1):
            for c in cases:
                row = run_case(settings, c, evidence[c], keep, rnd, log)
                w.writerow(row)
                f.flush()
                print(f"r{rnd} {c}: {row['status']} {row['seconds']}s bundle_problems={row['bundle_problems']} "
                      f"evidence_problems={row['evidence_problems']}")

    import agent_passrate_summary as aps  # noqa: E402
    aps.main(["--runs", str(keep), "--out", str(args.evidence_dir), "--csv", str(csv_path)])


if __name__ == "__main__":
    main()
