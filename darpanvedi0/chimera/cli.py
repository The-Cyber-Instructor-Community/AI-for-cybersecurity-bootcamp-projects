"""Command line: python -m chimera <command> [options]

run             collect evidence for every case folder, score it, write bundles
lookup          look up one case's applicant-supplied identifiers (GitHub, IP, email, phone); saves lookups.json
leads           web-search leads for the reviewer (Claude API, info only); saves leads.json
section         print one family's section (exactly what the Case Reader tool returns)
check-bundle    run the Bundle Check on analyst output
check-evidence  run the Evidence Check on a final report
backtest        replay a watchlist in date order and measure the exact-match catch rate
evaluate        compare bands with cases/labels.csv (synthetic demo cases only)
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from . import application, idcheck, leads, lookups, resume, templates, video, voice
from .backtest import backtest, format_report
from .bundle import assign_ids, read_section, write_bundle
from .checks import bundle_check, evidence_check
from .schema import FAMILIES, Signal
from .score import compute
from .watchlist import Watchlist


def _read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _load_corpus(folder) -> dict:
    return {p.name: p.read_text(encoding="utf-8", errors="replace") for p in sorted(Path(folder).glob("*.txt"))}


def _failure(error: BaseException) -> str:
    """One line naming the error, for an evidence line and the run's printout."""
    return " ".join(f"{type(error).__name__}: {error}".split())[:160].replace('"', "'")


def failed_signal(family: str, check: str, error: BaseException) -> Signal:
    """The info line a case gets when one of its checks raised (Oct 23 review, finding 2).

    A check that breaks on one file (an empty recording, a PDF that is not a PDF, ffmpeg missing) must not stop the
    batch or leave summary.json stale, and the reviewer must see that the check did not run rather than a clean
    case. The line carries no points.
    """
    code = check.replace(" ", "_") + "_failed"
    return Signal(family, code, "info", f"The {check} failed on this case ({_failure(error)}), so it added no evidence.",
                  data={"error": _failure(error)})


def _collect(family: str, check: str, fn, *args) -> list[Signal]:
    """Run one check; when it raises, print why and give the case the failure line instead."""
    try:
        return fn(*args)
    except Exception as error:  # noqa: BLE001 - every check's own error is one case's business, not the batch's
        print(f"  {check} failed: {_failure(error)}")
        return [failed_signal(family, check, error)]


def cmd_run(args) -> None:
    watchlist = Watchlist.load(args.watchlist) if args.watchlist else None
    case_dirs = sorted(p for p in Path(args.cases).iterdir() if (p / "application.json").is_file())
    if not case_dirs:
        sys.exit(f"No case folders with an application.json under {args.cases}")

    cases, resumes, names, resume_signals = {}, {}, {}, {}
    for d in case_dirs:
        try:
            case = json.loads(_read(d / "application.json"))
            case = leads.apply_saved(d, lookups.apply_saved(d, case))  # replays lookups.json and leads.json, no network
        except Exception as error:  # noqa: BLE001 - a case folder nothing can be read from is skipped, not fatal
            print(f"Skipping {d.name}: its application.json could not be read ({_failure(error)})")
            continue
        cid = case.get("case_id", d.name)
        cases[cid] = (d, case)
        try:
            resumes[cid], resume_signals[cid] = resume.analyze(d)
        except Exception as error:  # noqa: BLE001 - a resume that cannot be opened: the case is scored without it
            print(f"  resume check failed on {cid}: {_failure(error)}")
            resumes[cid], resume_signals[cid] = "", [failed_signal("A2", "resume check", error)]
        names[cid] = (case.get("candidate") or {}).get("name", "")
    if not cases:
        sys.exit(f"No case under {args.cases} could be read")

    corpus = _load_corpus(args.resume_corpus) if args.resume_corpus else None
    try:
        reuse, reuse_error = templates.find_reuse(resumes, names, args.template_threshold, corpus), None
    except Exception as error:  # noqa: BLE001 - the batch comparison failed: every case says so, none is lost
        print(f"  template check failed: {_failure(error)}")
        reuse, reuse_error = {}, error
    meta = {
        "watchlist": watchlist.source if watchlist else None,
        "watchlist_stats": watchlist.stats() if watchlist else None,
        "template_threshold": args.template_threshold,
        "cases_in_batch": len(cases),
    }

    out, rows = Path(args.out), []
    for cid, (d, case) in cases.items():
        signals = (
            _collect("A1", "video check", video.analyze, d, case, out / cid / video.EVIDENCE_FRAMES)
            + _collect("A1", "voice check", voice.analyze, d, case)
            + resume_signals[cid]
            + ([failed_signal("A2", "template check", reuse_error)] if reuse_error
               else templates.signals_for(reuse[cid], args.template_threshold))
            + _collect("A3", "application check", application.analyze, case, watchlist)
            + _collect("A3", "ID check", idcheck.analyze, d, case)
        )
        signals = assign_ids(signals)
        result = compute(signals)
        write_bundle(out / cid, cid, signals, result, meta)
        rows.append({
            "case_id": cid,
            "score": result.score,
            "band": result.band,
            **result.family_points,
            "most_critical": result.most_critical.code if result.most_critical else "",
            "note": " ".join(result.notes),
        })

    wl = (f"{watchlist.source}: {meta['watchlist_stats']['rows']} rows, "
          f"{meta['watchlist_stats']['rings']} rings") if watchlist else "none"
    table = ["| Case | Score | Band | A1 | A2 | A3 | Most critical | Note |", "|---|---|---|---|---|---|---|---|"]
    table += [f"| {r['case_id']} | {r['score']}/10 | {r['band']} | {r['A1']} | {r['A2']} | {r['A3']} | "
              f"{r['most_critical'] or '-'} | {r['note'] or ''} |" for r in rows]
    summary = "\n".join(["# Chimera run summary", "", f"Watchlist: {wl}", "", *table, ""])
    (out / "summary.md").write_text(summary, encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"meta": meta, "cases": rows}, indent=2), encoding="utf-8")
    print(summary)


def cmd_lookup(args) -> None:
    """Live lookups for one case the operator owns or has consent for; writes <case>/lookups.json."""
    case_dir = Path(args.case)
    case = json.loads(_read(case_dir / "application.json"))
    lookups.load_env()
    record = lookups.run_lookups(case)
    (case_dir / "lookups.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    for name, found in record["sources"].items():
        print(f"{name:9s} {json.dumps(found, ensure_ascii=False)}")
    for reason in record["skipped"]:
        print(f"skipped   {reason}")
    print(f"{len(record['calls'])} request(s). Saved {case_dir / 'lookups.json'}; "
          f"python -m chimera run replays it.")


def cmd_leads(args) -> None:
    """Claude web-search leads for one case (consent required); writes <case>/leads.json."""
    case_dir = Path(args.case)
    lookups.load_env()
    record = leads.run_leads(json.loads(_read(case_dir / "application.json")))
    (case_dir / "leads.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    for lead in record["leads"]:
        print(f"- {lead['claim']}\n    {lead['url']}\n    \"{lead['quote']}\"")
    for reason in record["skipped"]:
        print(f"skipped: {reason}")
    print(f"{len(record['leads'])} lead(s), {record.get('dropped', 0)} dropped. Saved {case_dir / 'leads.json'}.")


def cmd_section(args) -> None:
    print(read_section(_read(args.evidence), args.family))


def cmd_check_bundle(args) -> None:
    print(bundle_check(_read(args.evidence), _read(args.analysts)))


def cmd_check_evidence(args) -> None:
    print(evidence_check(_read(args.evidence), _read(args.report)))


def cmd_backtest(args) -> None:
    print(format_report(backtest(Watchlist.load(args.watchlist), start=args.start)))


def cmd_evaluate(args) -> None:
    with open(args.labels, newline="", encoding="utf-8") as f:
        labels = list(csv.DictReader(f))
    table = ["| Case | Truth | Scenario | Expected | Got | Match |", "|---|---|---|---|---|---|"]
    counts = {"fake_flagged": 0, "fake_missed": 0, "real_flagged": 0, "real_clear": 0}
    for lab in labels:
        ev = json.loads(_read(Path(args.out) / lab["case_id"] / "evidence.json"))
        flagged = ev["band"] in ("Review", "High")
        key = ("fake_" if lab["label"] == "fake" else "real_") + (
            ("flagged" if flagged else "missed") if lab["label"] == "fake" else ("flagged" if flagged else "clear"))
        counts[key] += 1
        ok = "yes" if ev["band"] == lab["expected_band"] else "NO"
        table.append(f"| {lab['case_id']} | {lab['label']} | {lab['scenario']} | {lab['expected_band']} | "
                     f"{ev['band']} ({ev['score']}/10) | {ok} |")
    print("\n".join(table))
    print(f"\nFakes flagged (Review or High): {counts['fake_flagged']} of {counts['fake_flagged'] + counts['fake_missed']}")
    print(f"Real applicants flagged: {counts['real_flagged']} of {counts['real_flagged'] + counts['real_clear']}")
    print("These are synthetic demo cases built to show each rule. They are not an accuracy result.")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="chimera", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="collect evidence and score every case")
    p.add_argument("--cases", default="cases")
    p.add_argument("--watchlist", help="xlsx or csv with the 20-column watchlist layout")
    p.add_argument("--out", default="out")
    p.add_argument("--template-threshold", type=float, default=templates.DEFAULT_THRESHOLD)
    p.add_argument("--resume-corpus", help="folder of .txt resumes to compare against (optional)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("lookup", help="live lookups for one case (GitHub, IP, email, phone); saves lookups.json")
    p.add_argument("case", help="the case folder, for example cases/case_demo")
    p.set_defaults(func=cmd_lookup)

    p = sub.add_parser("leads", help="Claude web-search leads for one case (info only); saves leads.json")
    p.add_argument("case", help="the case folder")
    p.set_defaults(func=cmd_leads)

    p = sub.add_parser("section", help="print one family's evidence section")
    p.add_argument("--evidence", required=True)
    p.add_argument("--family", required=True, choices=list(FAMILIES))
    p.set_defaults(func=cmd_section)

    p = sub.add_parser("check-bundle", help="Bundle Check on analyst output")
    p.add_argument("--evidence", required=True)
    p.add_argument("--analysts", required=True, help="text file with the analysts' reports")
    p.set_defaults(func=cmd_check_bundle)

    p = sub.add_parser("check-evidence", help="Evidence Check on a final report")
    p.add_argument("--evidence", required=True)
    p.add_argument("--report", required=True)
    p.set_defaults(func=cmd_check_evidence)

    p = sub.add_parser("backtest", help="exact-match catch rate, replaying the watchlist by date")
    p.add_argument("--watchlist", required=True)
    p.add_argument("--start", default="2026-01-01", help="test personas first seen on or after this date")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("evaluate", help="compare bands with cases/labels.csv")
    p.add_argument("--labels", default="cases/labels.csv")
    p.add_argument("--out", default="out")
    p.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    args.func(args)
