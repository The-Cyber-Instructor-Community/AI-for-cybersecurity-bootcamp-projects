"""Summarize an agent pass-rate run: how many runs passed both code checks, and what failed in the others.

tools/agent_passrate.ps1 (on the PC) sends every synthetic case through the LangFlow agents via the Console and keeps,
per run, r<round>_<case>_bundle_check.txt, r<round>_<case>_evidence_check.txt and r<round>_<case>_report.md. This
script reads those with out/<case>/evidence.md and gives every problem a kind.

- A quote that is not verbatim is looked up again: a capital-letter difference, a quote from another line of the same
  case, a quote from another case's bundle (the shared chat memory of Oct 19), or a quote found in no bundle.
- Every report is scanned for emails, watchlist rows and ring IDs that belong to another case's bundle.
- Evidence IDs named outside the bundle are matched against the IDs the prompts use as examples.
- A "point the same way" sentence that cites an info line is flagged: the checks before Oct 19 passed it, but the
  sentence is wrong (an info line has no finding to point anywhere).
- --recheck runs the current chimera/checks.py again on the saved texts: the Evidence Check on every saved report, the
  Bundle Check where the run kept the analysts' text (r<round>_<case>_analysts.txt, kept since Oct 19).

Synthetic cases only. Usage:
    python scripts/agent_passrate_summary.py --runs data/scores/agent_passrate [--out out] [--prompts langflow/prompts]
        [--csv data/scores/agent_passrate.csv] [--recheck]
Prints the summary and writes <runs>/problems.csv.
"""
import argparse
import csv
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chimera.checks import CITATION, REPORT_EVIDENCE, bundle_check, evidence_check, parse_bundle  # noqa: E402

RUN_FILE = re.compile(r"^r(\d+)_(case_\d+)_evidence_check\.txt$")
IDENTIFIER = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\bW-\d{4}\b|\bR-\d{3}\b")
QUOTED = re.compile(r"[\"“]([^\"”\n]{12,})[\"”]")
CITATION_PROBLEM = re.compile(r"^(E\d\.\d+) \[(A\d)\]: (.*?)\.?$")

KINDS = [  # first match wins; patterns are searched in one problem (or one issue of a citation problem)
    (r'Point the same way" cites an info line', "same-way sentence cites an info line"),
    (r"needs scored findings from two families", "same-way sentence within one family"),
    (r'Point the same way" cites no evidence IDs', "same-way sentence without IDs"),
    (r"A contradiction cites", "contradiction cites fewer than two lines"),
    (r"which this case's evidence does not contain", "names an identifier the case does not contain"),
    (r"quote does not appear verbatim", "quote not verbatim"),
    (r"does not match the ID's family", "wrong family tag"),
    (r"ID is not in the bundle|cites IDs that are not in the bundle", "cites an ID not in the bundle"),
    (r"names? IDs that are not in the bundle", "names an ID not in the bundle"),
    (r"Scored evidence left out", "scored evidence left out of the report"),
    (r"did not cite", "analyst skipped a scored line"),
    (r"report missing", "analyst report missing"),
    (r"no 'STATUS: COMPLETE'", "analyst did not finish"),
    (r"cites another family's evidence", "cites another family's evidence"),
    (r"Code line not copied verbatim", "code line changed"),
    (r"has no Evidence: line", "finding without an Evidence line"),
    (r"no (?:analysts' text|report) was returned", "no output"),
    (r"questions", "questions for the candidate"),
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def kind_of(text: str) -> str:
    return next((k for pattern, k in KINDS if re.search(pattern, text)), "other")


def problem_lines(check_text: str, header: str) -> list[str]:
    """The '- ...' lines under the check's problems header, without '- none'."""
    at = check_text.find(header)
    if at == -1:
        return []
    out = []
    for line in check_text[at + len(header):].splitlines()[1:]:
        if not line.strip():
            break
        if line.startswith("- ") and line.strip() != "- none":
            out.append(line[2:].strip())
    return out


def squash(s: str) -> str:
    return re.sub(r"[^a-z0-9@]+", " ", s.lower()).strip()


def quote_origin(quote: str, eid: str, case: str, bundles: dict) -> str:
    """Where a quote that is not verbatim in its evidence line came from."""
    own, q = bundles[case], quote.strip()
    line = own[eid]["text"]
    if q.lower() in line.lower():
        return "capital letters only"
    if squash(q) and squash(q) in squash(line):
        return "spacing or punctuation only"
    if any(q.lower() in info["text"].lower() for other, info in own.items() if other != eid):
        return "from another line of this case"
    others = [c for c, b in bundles.items() if c != case and any(q.lower() in i["text"].lower() for i in b.values())]
    if others:
        return "from another case's bundle (" + ", ".join(others) + ")"
    return "in no bundle (reworded or made up)"


def prompt_example_ids(prompts: Path | None) -> set:
    if not prompts or not prompts.exists():
        return set()
    text = "\n".join(read(p) for p in sorted(prompts.glob("*.md")))
    return {f"E{a}.{b}" for a, b in CITATION.findall(text)}


def analyse_run(rnd: int, case: str, runs: Path, raw: dict, bundles: dict, examples: set, recheck=False) -> dict:
    bundle_text = read(runs / f"r{rnd}_{case}_bundle_check.txt")
    evidence_text = read(runs / f"r{rnd}_{case}_evidence_check.txt")
    report = read(runs / f"r{rnd}_{case}_report.md")
    analysts = read(runs / f"r{rnd}_{case}_analysts.txt")
    if recheck and case in raw:
        evidence_text = evidence_check(raw[case], report) if report else evidence_text
        bundle_text = bundle_check(raw[case], analysts) if analysts else bundle_text
    own = bundles.get(case, {})
    rows = []

    def add(check, kind, detail=""):
        rows.append({"round": rnd, "case": case, "check": check, "kind": kind, "detail": detail})

    for check, text, header in (("bundle", bundle_text, "BUNDLE PROBLEMS / COVERAGE GAPS"),
                                ("evidence", evidence_text, "EVIDENCE PROBLEMS")):
        for problem in problem_lines(text, header):
            m = CITATION_PROBLEM.match(problem) if check == "evidence" else None
            issues = [(f"{m.group(1)} [{m.group(2)}]: ", i) for i in m.group(3).split("; ")] if m else [("", problem)]
            for prefix, issue in issues:
                kind = kind_of(issue)
                if kind == "quote not verbatim":
                    continue                                   # recomputed from the report below, with its origin
                detail = prefix + issue
                if kind == "names an ID not in the bundle":
                    named = {f"E{a}.{b}" for a, b in CITATION.findall(issue)}
                    if named and named <= examples:
                        detail += " (the prompts use it as an example)"
                add(check, kind, detail)

    for m in REPORT_EVIDENCE.finditer(report):
        eid, _digit, quoted, _tag = m.groups()
        if eid in own and quoted and quoted.strip() and quoted.strip() not in own[eid]["text"]:
            add("evidence", "quote not verbatim",
                f'{eid} "{quoted.strip()[:70]}": {quote_origin(quoted, eid, case, bundles)}')

    mine = raw.get(case, "")
    for ident in sorted(set(IDENTIFIER.findall(report))):
        if ident not in mine:
            others = [c for c, text in raw.items() if c != case and ident in text]
            if others:
                add("scan", "from another case", f"{ident} ({', '.join(others)})")
    for q in sorted(set(QUOTED.findall(report))):
        if q.lower() not in mine.lower():
            others = [c for c, text in raw.items() if c != case and q.lower() in text.lower()]
            if others:
                add("scan", "from another case", f'"{q[:70]}" ({", ".join(others)})')

    checked = "Point the same way" in evidence_text            # the Evidence Check flags it itself since Oct 19
    for line in [] if checked else report.splitlines():
        if "point the same way" in line:
            cited = [f"E{a}.{b}" for a, b in CITATION.findall(line)]
            info = [i for i in cited if i in own and not own[i]["scored"]]
            if info:
                add("scan", "same-way sentence cites an info line", f"{', '.join(info)}: {line.strip()[:110]}")

    return {"round": rnd, "case": case, "bundle_ok": "- none" in bundle_text, "evidence_ok": "- none" in evidence_text,
            "rows": rows}


def summarize(results: list[dict], seconds: list[float]) -> list[str]:
    n = len(results)
    passed = [r for r in results if r["bundle_ok"] and r["evidence_ok"]]
    lines = [f"runs: {n}; both checks passed: {len(passed)} ({100 * len(passed) / max(n, 1):.0f}%); "
             f"Bundle Check passed: {sum(r['bundle_ok'] for r in results)}; "
             f"Evidence Check passed: {sum(r['evidence_ok'] for r in results)}"]
    if seconds:
        lines.append(f"seconds per run: median {statistics.median(seconds):.0f}, max {max(seconds):.0f}")
    by_round, by_case = defaultdict(list), defaultdict(list)
    for r in results:
        ok = r["bundle_ok"] and r["evidence_ok"]
        by_round[r["round"]].append(ok)
        by_case[r["case"]].append(ok)
    lines.append("by round: " + "; ".join(f"r{k} {sum(v)}/{len(v)}" for k, v in sorted(by_round.items())))
    lines.append("by case: " + "; ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(by_case.items())))
    occurrences = Counter(row["kind"] for r in results for row in r["rows"])
    runs_with = Counter(kind for r in results for kind in {row["kind"] for row in r["rows"]})
    lines.append("")
    lines.append("problems (runs affected / occurrences):")
    for kind, count in occurrences.most_common():
        lines.append(f"  {kind}: {runs_with[kind]} / {count}")
    origins = Counter(row["detail"].rsplit(": ", 1)[-1] for r in results for row in r["rows"]
                      if row["kind"] == "quote not verbatim")
    if origins:
        lines.append("  quotes not verbatim, by origin: " + "; ".join(f"{k} {v}" for k, v in origins.most_common()))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=Path, default=ROOT / "data" / "scores" / "agent_passrate")
    ap.add_argument("--out", type=Path, default=ROOT / "out", help="the pipeline output folder with <case>/evidence.md")
    ap.add_argument("--prompts", type=Path, default=ROOT / "langflow" / "prompts")
    ap.add_argument("--csv", type=Path, default=None, help="agent_passrate.csv, for the seconds per run")
    ap.add_argument("--recheck", action="store_true", help="run the current checks again on the saved texts")
    args = ap.parse_args(argv)

    raw = {p.parent.name: read(p) for p in sorted(args.out.glob("case_*/evidence.md"))}
    bundles = {case: parse_bundle(text) for case, text in raw.items()}
    examples = prompt_example_ids(args.prompts)
    runs = sorted((int(m.group(1)), m.group(2)) for p in args.runs.glob("r*_case_*_evidence_check.txt")
                  if (m := RUN_FILE.match(p.name)))
    results = [analyse_run(rnd, case, args.runs, raw, bundles, examples, args.recheck) for rnd, case in runs]
    seconds = []
    if args.csv and args.csv.exists():
        with open(args.csv, encoding="utf-8-sig", newline="") as f:
            seconds = [float(r["seconds"]) for r in csv.DictReader(f) if r.get("status") == "done" and r.get("seconds")]

    print(f"Agent pass rate: {args.runs}")
    if args.recheck:
        kept = sum((args.runs / f"r{rnd}_{case}_analysts.txt").exists() for rnd, case in runs)
        print(f"checks run again with the current code: Evidence Check on every report, Bundle Check on {kept} of "
              f"{len(runs)} runs (the others keep the saved Bundle Check)")
    print("\n".join(summarize(results, seconds)))
    name = "problems_recheck.csv" if args.recheck else "problems.csv"
    with open(args.runs / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["round", "case", "check", "kind", "detail"])
        w.writeheader()
        for r in results:
            w.writerows(r["rows"])
    print(f"\nwrote {args.runs / name}")
    return results


if __name__ == "__main__":
    main()
