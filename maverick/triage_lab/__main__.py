"""Command line: python -m triage_lab <command> [options]

  generate                 build the labelled dataset (stage 1)
  run                      one experiment: stages 2-6 for every incident
  stage <name>             a named batch of runs (what the Kaggle notebook uses), always resumable:
                             main | ablations | agentic | bigger_model | heldout | repeat | gaploop | score | all
  ablations                payload-only, no-context, no-RAG, poisoned-RAG, fp-framing, no-playbook runs
  grade                    investigation accuracy only (also part of score); --judge ollama for an LLM judge
  repeat                   k repeated runs for the consistency metric (pass^k)
  score                    stage 7: metrics.json + REPORT.md + Navigator layer
  demo                     the demo script
  gaploop                  draft, backtest and refine rules for missed techniques
  cases                    write a readable handover case file per incident (results/cases/<run>/)
  regate                   re-apply the current gates (v2 = v1 + multi-stage chain gate) to every finished
                           run from its saved rows (no model needed), then score
  ingest-windows           add live Atomic Red Team / Sysmon events
  all                      generate + every run + gaploop + score + demo

Common options: --backend stub|ollama|replay   --model qwen2.5:7b   --resume
                --dataset main|heldout|small   (heldout: another seed, never tuned on;
                                                small: ~27 incidents for a laptop, see docs/LOCAL_LANGFLOW.md)
  serve                    chat front-end for the demo (LangFlow Playground or any chat UI): http://localhost:8765/ask
  doctor                   check Ollama (and LangFlow flows, with --backend langflow) before a long run
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# every named experiment: run name -> options
RUNS = {
    "main": {},
    "payload_only": {"mode": "payload"},
    "no_context": {"context": False},
    "no_rag": {"rag": False},
    "poisoned_rag": {"poison": True},
    "main_critic": {"critic": True},
    "agentic": {"mode": "agentic"},
    "agentic_critic": {"mode": "agentic", "critic": True},
    "fp_framing": {"framing": True},                  # a colleague asks "is this a false positive?"
    "no_playbook": {"rag": False, "playbook": False},  # no knowledge notes, no DECIDING checklist
}
STAGES = {
    "main": ["main"],
    "ablations": ["payload_only", "no_context", "no_rag", "poisoned_rag", "fp_framing", "no_playbook"],
    "agentic": ["agentic", "agentic_critic", "main_critic"],
    "bigger_model": ["main", "agentic"],
}


def _tag(model: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", model.lower()).strip("-")


def main(argv: list[str] | None = None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--backend", choices=["stub", "ollama", "replay", "langflow"])
    common.add_argument("--model", help="override agent.model, e.g. qwen2.5:7b")
    common.add_argument("--resume", action="store_true", help="skip incidents already finished in a run")
    common.add_argument("--dataset", choices=["main", "heldout", "small"], default="main",
                        help="heldout = data_heldout/ (another seed); small = data_small/ (~27 incidents)")

    p = argparse.ArgumentParser(prog="triage_lab", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate", parents=[common])

    r = sub.add_parser("run", parents=[common])
    r.add_argument("--name", default="main")
    r.add_argument("--mode", choices=["evidence", "payload", "agentic"], default="evidence")
    r.add_argument("--no-context", action="store_true")
    r.add_argument("--no-rag", action="store_true")
    r.add_argument("--poison", action="store_true")
    r.add_argument("--critic", action="store_true", help="add the critic agent")
    r.add_argument("--limit", type=int, help="only the first N incidents (quick test)")

    st = sub.add_parser("stage", parents=[common])
    st.add_argument("name", choices=list(STAGES) + ["heldout", "repeat", "gaploop", "regate", "score", "all"])
    st.add_argument("-k", type=int, default=3, help="repeats for the repeat stage")
    st.add_argument("--limit", type=int)

    a = sub.add_parser("ablations", parents=[common])
    a.add_argument("--only", nargs="*", choices=list(RUNS))
    k = sub.add_parser("repeat", parents=[common])
    k.add_argument("-k", type=int, default=3)
    k.add_argument("--temperature", type=float, default=0.7)
    sub.add_parser("score", parents=[common])
    gr = sub.add_parser("grade", parents=[common])
    gr.add_argument("--judge", choices=["stub", "ollama"], help="LLM judge for misattribution (default: rules)")
    sub.add_parser("doctor", parents=[common])
    sub.add_parser("regate", parents=[common])
    sv = sub.add_parser("serve", parents=[common])
    sv.add_argument("--port", type=int, default=8765)
    d = sub.add_parser("demo", parents=[common])
    d.add_argument("--run", default="main")
    sub.add_parser("gaploop", parents=[common])
    cs = sub.add_parser("cases", parents=[common])
    cs.add_argument("--run", nargs="*", help="run names (default: every run)")
    w = sub.add_parser("ingest-windows")
    w.add_argument("--events", required=True)
    w.add_argument("--labels", required=True)
    w.add_argument("--shift-to")
    w.add_argument("--as-user")
    sub.add_parser("all", parents=[common])

    args = p.parse_args(argv)
    dataset = getattr(args, "dataset", "main")
    if args.cmd == "stage" and args.name == "heldout":
        dataset = "small_heldout" if dataset == "small" else "heldout"
    if dataset != "main":
        use_dataset(dataset)
    if getattr(args, "model", None):
        from .config import override
        override("agent.model", args.model)
    backend, resume = getattr(args, "backend", None), getattr(args, "resume", False)

    if args.cmd in ("generate", "all"):
        from .generate import main as gen
        gen()
    if args.cmd == "run":
        from .pipeline import run
        run(args.name, backend, args.mode, not args.no_context, not args.no_rag, args.poison,
            limit=args.limit, critic=args.critic, resume=resume)
    if args.cmd == "ablations":
        _runs(args.only or STAGES["ablations"], backend, resume)
    if args.cmd == "all":
        _runs(list(RUNS), backend, resume)
    if args.cmd == "repeat":
        _repeat(backend, args.k, args.temperature, resume)
    if args.cmd == "stage":
        _stage(args, backend)
    if args.cmd in ("gaploop", "all"):
        from .gaploop import run as gap
        for r in gap(backend):
            print(json.dumps(r, default=str))
    if args.cmd in ("score", "all", "repeat"):
        _score()
    if args.cmd == "grade":
        _grade(args.judge)
    if args.cmd == "serve":
        from .chatserver import serve
        serve(args.port, backend)
    if args.cmd == "regate":
        _regate()
        _score()
    if args.cmd == "doctor":
        from .agent import doctor
        sys.exit(0 if doctor(backend) else 1)
    if args.cmd in ("demo", "all"):
        from .demo import main as demo
        print(demo(getattr(args, "run", "main")))
    if args.cmd == "cases":
        _cases(args.run)
    if args.cmd == "ingest-windows":
        from pathlib import Path

        from .ingest.windows import ingest
        print(ingest(Path(args.events), Path(args.labels), args.shift_to, args.as_user))


def use_dataset(name: str) -> None:
    """Point every stage at another dataset folder and its own results folder.
      heldout        same size, another seed: checks a prompt tuned on the main dataset
      small          ~27 incidents, every scenario type: for a laptop (Ollama + LangFlow, 3B)
      small_heldout  small, another seed"""
    from .config import override, settings
    gen = settings()["generator"]
    override("paths.data_dir", f"data_{name}")
    override("paths.results_dir", f"results_{name}")
    if name.startswith("small"):
        for k, v in settings().get("small", {}).items():
            override(f"generator.{k}", v)
    if name.endswith("heldout"):
        override("generator.seed", gen.get("heldout_seed", 11))


def _grade(judge_backend) -> None:
    from .config import path
    from .grading import Judge, grade_run
    from .metrics import load_pipeline, load_truth
    from .schema import read_jsonl
    labels, by_event, scenarios = load_truth()
    _, incidents, _, _ = load_pipeline()
    judge = Judge(judge_backend)
    for f in sorted((path("results_dir") / "runs").glob("*.jsonl")):
        if f.stem.startswith("repeat_"):
            continue
        g = grade_run(f.stem + ("" if judge.label == "deterministic" else "__judged"), list(read_jsonl(f)),
                      incidents, by_event, scenarios, labels, judge)
        print(f"{f.stem:<24} investigation score {g['investigation_score_mean']} (hard fails {g['hard_fails']}/"
              f"{g['incidents']}) misattribution rate {g['misattribution']['rate']} grader {g['grader']}")


def _regate() -> None:
    """Re-apply the gates to every finished run WITHOUT the model: controls v2 is v1 plus the
    multi-stage chain gate, so each saved row's v1 decision is kept and the extra gate is applied
    to it. Needs no saved model answers, so it gives the same result on Kaggle and on a laptop."""
    import json

    from .config import path, settings
    from .schema import read_jsonl
    tactic = settings()["attack"]["tactic"]
    need = settings()["gates"].get("multi_stage_min_tactics")
    v2 = settings()["gates"].get("controls_version", "v1") >= "v2"
    for f in sorted((path("results_dir") / "runs").glob("*.jsonl")):
        rows = list(read_jsonl(f))
        flipped = 0
        for r in rows:
            r.setdefault("assured_v1", r["assured"])
            reasons = [g for g in r.get("gate_reasons", []) if not g.startswith("multi-stage chain")]
            assured = r["assured_v1"]
            tactics = sorted({tactic[t] for t in r.get("techniques_detected", []) if t in tactic})
            if v2 and need and assured == "close" and len(tactics) >= need:
                assured = "escalate"
                reasons.append(f"multi-stage chain: {len(tactics)} ATT&CK tactics ({', '.join(tactics)})")
                flipped += 1
            r["assured"], r["gate_reasons"] = assured, reasons
            r["controls_version"] = "v2" if v2 else "v1"
        f.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        print(f"regated {f.stem}: {len(rows)} incidents, {flipped} closes escalated by the v2 gate")


def _runs(names: list[str], backend, resume: bool, suffix: str = "", limit: int | None = None) -> None:
    from .pipeline import run
    for name in names:
        print(f"\n--- run: {name + suffix} {RUNS[name] or ''}")
        run(name + suffix, backend, quiet=False, resume=resume, limit=limit, **RUNS[name])


def _repeat(backend, k: int, temperature: float, resume: bool) -> None:
    from .pipeline import run
    for i in range(k):
        print(f"--- repeat {i + 1}/{k}")
        run(f"repeat_{i + 1}", backend, temperature=temperature, run_index=i + 1, quiet=True, resume=resume)


def _stage(args, backend) -> None:
    from .config import path, settings
    if not (path("data_dir") / "events.jsonl").exists():
        from .generate import main as gen
        gen()
    if args.name in STAGES:
        suffix = f"__{_tag(settings()['agent']['model'])}" if args.name == "bigger_model" else ""
        _runs(STAGES[args.name], backend, resume=True, suffix=suffix, limit=args.limit)
    elif args.name == "regate":                       # no GPU, no model: works from the saved rows
        _regate()
    elif args.name == "heldout":                      # data_dir already points at data_heldout/
        _runs(["main"], backend, resume=True, limit=args.limit)
    elif args.name == "repeat":
        _repeat(backend, args.k, 0.7, resume=True)
    elif args.name == "gaploop":
        from .gaploop import run as gap
        for r in gap(backend):
            print(json.dumps(r, default=str))
    elif args.name == "all":
        for s in ("main", "ablations", "agentic"):
            _runs(STAGES[s], backend, resume=True, limit=args.limit)
        from .gaploop import run as gap
        gap(backend)
    _score()


def _score() -> None:
    from .config import path
    from .metrics import score
    from .navigator import export
    from .report import write
    runs_dir = path("results_dir") / "runs"
    present = {p.stem for p in runs_dir.glob("*.jsonl")}
    names = [n for n in RUNS if n in present] + sorted(n for n in present
                                                        if n not in RUNS and not n.startswith("repeat_"))
    repeats = sorted(n for n in present if n.startswith("repeat_"))
    m = score(names, repeats or None)
    export(m)
    write(m)
    _cases(names, quiet=True)
    print(f"Wrote {path('results_dir').name}/metrics.json, REPORT.md, navigator_layer.json "
          f"({len(names)} runs scored{', ' + str(len(repeats)) + ' repeats' if repeats else ''})")


def _cases(names=None, quiet: bool = False) -> None:
    from .casefile import write_cases
    from .config import path
    runs_dir = path("results_dir") / "runs"
    names = names or sorted(p.stem for p in runs_dir.glob("*.jsonl") if not p.stem.startswith("repeat_"))
    for n in names:
        k = write_cases(n)
        if not quiet:
            print(f"wrote {k} case files to results/cases/{n}/")


if __name__ == "__main__":
    main(sys.argv[1:])
