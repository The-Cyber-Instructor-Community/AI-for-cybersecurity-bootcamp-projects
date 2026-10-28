"""Sentinel command line.

    python -m sentinel.cli analyze targets/helpdeskbot            # Recon + Threat Model and Static Scan, in parallel
    python -m sentinel.cli score   targets/helpdeskbot            # compare findings with answer_key.yaml

Results go to runs/<target name>/: system_map.json, threats.json, threat_model.md, findings.json.
Set SENTINEL_LLM=anthropic to turn on the optional LLM steps (default: off, zero tokens).
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from sentinel import llm
from sentinel.agents import api_discovery, autoprobe, probe as probe_agent, recon, recon_llm, redteam, remediate as remediate_agent, report as report_agent, static_scan, threat_model
from sentinel.models import Finding, Threat
from sentinel.score import posture, score

RUNS = Path("runs")


def _save(path: Path, items) -> None:
    path.write_text(json.dumps([i.model_dump() for i in items], indent=2))


def _merge_llm_findings(target: Path, rule_findings, out: Path, budget: llm.Budget, system_map=None):
    """Add LLM-proposed weaknesses the rules missed (de-duped by family+file), and save the map."""
    understanding = recon_llm.understand(target, system_map, budget)
    if understanding is None:                       # LLM off: nothing to add, don't touch the file
        return rule_findings
    (out / "app_understanding.json").write_text(understanding.model_dump_json(indent=2))
    have = {(f.check_family, f.file) for f in rule_findings}
    extra = [f for f in recon_llm.to_findings(understanding) if (f.check_family, f.file) not in have]
    if understanding.weaknesses:
        print(f"  LLM recon: {len(understanding.weaknesses)} weakness(es), {len(extra)} new -> app_understanding.json")
    else:
        print(f"  LLM recon: {understanding.summary[:90]}")
    return rule_findings + extra


def analyze(target: Path) -> Path:
    out = RUNS / target.name
    out.mkdir(parents=True, exist_ok=True)
    bud_rt, bud_s = llm.Budget(20_000), llm.Budget(20_000)

    # Recon (ast) and the Semgrep rules don't depend on each other -> run in parallel.
    with ThreadPoolExecutor(max_workers=2) as pool:
        map_future = pool.submit(recon.build_system_map, target)
        rules_future = pool.submit(static_scan.run_rules, target)
        system_map = map_future.result()
        rule_findings = rules_future.result()
    (out / "system_map.json").write_text(system_map.model_dump_json(indent=2))

    # Static API discovery (no LLM, no network): port + endpoint + request/reply shape for auto-probing.
    hints = api_discovery.discover_api_static(target)
    (out / "api_hints.json").write_text(hints.model_dump_json(indent=2))
    if hints.endpoints or hints.candidate_ports:
        print(f"  API hints: {hints.base_url or '?'}{(hints.endpoints or ['?'])[0]} "
              f"(field={hints.message_field or '?'}, reply={hints.reply_path or '?'}) -> api_hints.json")

    # Context filter: drop tool-scoped findings that aren't real agent tools (cuts real-repo noise).
    findings = static_scan.filter_by_map(rule_findings, system_map)
    if llm.enabled():
        findings = static_scan.triage(findings, target, bud_s)      # bounded: high/critical, capped
    findings = _merge_llm_findings(target, findings, out, llm.Budget(45_000), system_map)
    _save(out / "findings.json", findings)

    threats = threat_model.build_threat_model(system_map, bud_rt)
    _save(out / "threats.json", threats)
    (out / "threat_model.md").write_text(threat_model.to_markdown(system_map, threats))

    print(f"{len(threats)} threats, {len(findings)} findings -> {out}/")
    print(f"  tokens used by recon+threat_model: {bud_rt.used}")
    print(f"  tokens used by static_scan: {bud_s.used}")
    return out


def _load(out: Path, name: str, model):
    return [model(**x) for x in json.loads((out / name).read_text())]


def _dump_transcripts(out: Path, plan, results) -> Path:
    """Write every attack's payload and the target's full response, for eyeballing real-model runs."""
    by_id = {a.id: a for a in plan}
    lines = []
    for r in results:
        a = by_id[r.attack_id]
        lines += [f"### {r.attack_id}  (family {r.check_family}, {'SUCCESS' if r.success else 'blocked'})",
                  f"channel: {a.channel}   oracle: {a.oracle} -> {r.reason}",
                  f"payload:\n{a.payload.strip()}", f"transcript:\n{r.transcript}", "-" * 70]
    path = out / "attack_transcripts.txt"
    path.write_text("\n".join(lines))
    return path


def attack(target: Path, backend: str, llm_backend: str, dump: bool = False) -> Path:
    """Day 3: select attacks from threats+findings, run them, save results + an ASR summary."""
    out = RUNS / target.name
    threats = _load(out, "threats.json", Threat)
    findings = _load(out, "findings.json", Finding)
    corpus = redteam.load_corpus()
    plan = redteam.select(threats, findings, corpus)
    results = redteam.run_plan(plan, backend=backend, llm_backend=llm_backend)
    _save(out / "attack_results.json", results)
    _save(out / f"attack_results.{llm_backend}.json", results)   # kept per-model for the report
    if dump:
        print(f"  full transcripts -> {_dump_transcripts(out, plan, results)}")

    confirmed = [r for r in results if r.success]
    level_of = {a.id: a.level for a in plan}
    print(f"Ran {len(plan)} of {len(corpus)} corpus attacks (selection skipped {len(corpus) - len(plan)}).")
    print(f"Confirmed {len(confirmed)} exploits across {len({r.check_family for r in confirmed})} families; "
          f"tokens: {sum(r.tokens_used for r in results)}")
    for fam in sorted({r.check_family for r in results}):
        fr = [r for r in results if r.check_family == fam]
        print(f"  family {fam}: ASR {sum(r.success for r in fr)}/{len(fr)}")
    print("  by payload sophistication:")                       # obvious vs subtle = model's robustness boundary
    for lvl in ("obvious", "subtle"):
        lr = [r for r in results if level_of.get(r.attack_id) == lvl]
        if lr:
            print(f"    {lvl:8} ASR {sum(r.success for r in lr)}/{len(lr)}")
    return out


def _require_target(target: Path) -> None:
    if not target.is_dir():
        raise SystemExit(f"error: target not found: {target}\n"
                         f"  Point at a Python app directory, e.g. targets/helpdeskbot, or clone one first:\n"
                         f"    git clone <repo> /tmp/target && python -m sentinel.cli analyze /tmp/target")


def _require_analyzed(target: Path) -> Path:
    out = RUNS / target.name
    if not (out / "findings.json").exists():
        raise SystemExit(f"error: no analysis for '{target.name}' yet. Run this first:\n"
                         f"    python -m sentinel.cli analyze {target}")
    return out


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(prog="sentinel")
    p.add_argument("command", choices=["analyze", "attack", "probe", "autoprobe", "report", "remediate", "scan", "score"])
    p.add_argument("target", type=Path)
    p.add_argument("--backend", choices=["local", "docker"], default="local",
                   help="how to run the target (default: local subprocess)")
    p.add_argument("--target-llm", choices=["fake", "anthropic"], default="fake",
                   help="the TARGET app's model (default: fake = offline, free)")
    p.add_argument("--dump", action="store_true", help="write full per-attack transcripts for inspection")
    p.add_argument("--json", action="store_true", help="also print the full posture JSON (score command)")
    p.add_argument("--http", metavar="URL", help="probe a running app at this URL (HTTP adapter)")
    p.add_argument("--http-config", metavar="FILE", help="JSON config for the HTTP adapter (reply_path, extra_body, ...)")
    p.add_argument("--discover", metavar="BASE_URL", help="auto-discover the chat endpoint under this base URL and write sentinel.http.json")
    p.add_argument("--safe", action="store_true", help="dry-run: skip write-risky probes and flag any that trigger real tool calls")
    args = p.parse_args()
    if args.command == "analyze":
        _require_target(args.target)
        analyze(args.target)
    elif args.command == "attack":
        _require_analyzed(args.target)
        attack(args.target, args.backend, args.target_llm, args.dump)
    elif args.command == "probe":
        from sentinel.harness import http_adapter
        cfg_path = args.http_config or (args.target / "sentinel.http.json" if (args.target / "sentinel.http.json").exists() else None)
        http_config = None
        if args.http or cfg_path:
            conf = json.loads(Path(cfg_path).read_text()) if cfg_path else {}
            if args.http:
                conf["url"] = args.http                 # --http overrides the file's url
            http_config = http_adapter.HttpConfig(**conf)
        if http_config is None and not report_agent._has_harness(args.target):
            raise SystemExit("behavioral probing needs a running app: pass --http <url> (or add sentinel.http.json), "
                             "or wire a run_case harness. See RUNBOOK.md.")
        where = http_config.url if http_config else "run_case harness"
        results = probe_agent.run_probes(args.target, args.backend, args.target_llm, http_config=http_config)
        print(f"Probing {where}")
        hits = sum(r.success for r in results)
        print(f"Behavioral probes: {hits}/{len(results)} bad outcomes (judge: {args.target_llm})")
        for r in results:
            print(f"  {r.attack_id} family {r.check_family}: {'BAD' if r.success else 'ok '} - {r.reason}")
    elif args.command == "autoprobe":
        out = _require_analyzed(args.target)
        from sentinel.harness import http_adapter
        cfg_file = args.target / "sentinel.http.json"
        cfg_path = args.http_config or (cfg_file if cfg_file.exists() else None)
        http_config = None
        if args.http or cfg_path:
            conf = json.loads(Path(cfg_path).read_text()) if cfg_path else {}
            if args.http:
                conf["url"] = args.http
            http_config = http_adapter.HttpConfig(**conf)

        # Discovery: build a config against a base URL when we have none (or --discover was asked for).
        if args.discover:
            print(f"Discovering the chat API at {args.discover} ...")
            report: list[str] = []
            found = http_adapter.discover(args.discover, report=report)
            if not found:
                hint = ("\n  Candidates that responded but didn't fully match:\n    "
                        + "\n    ".join(report)) if report else ""
                raise SystemExit(f"Could not auto-discover a chat endpoint under {args.discover}.{hint}\n"
                                 "  Create sentinel.http.json by hand with the right url, message_field,\n"
                                 "  extra_body and reply_path (see RUNBOOK.md).")
            http_config = found
            cfg_file.write_text(found.model_dump_json(indent=2))
            print(f"  found {found.url} (message_field={found.message_field}, reply_path={found.reply_path}) "
                  f"-> wrote {cfg_file}")

        # Auto-config: no config yet? Try the static API hints from `analyze`, then network discovery.
        if http_config is None:
            hints_file = out / "api_hints.json"
            if hints_file.exists():
                hints = api_discovery.ApiHints(**json.loads(hints_file.read_text()))
                # A blanked id-like field (e.g. agent_id from a negative-test example) -> ask the live app.
                blank = [k for k, v in hints.extra_fields.items() if v is None and api_discovery._is_id_like(k)]
                if blank:
                    for port in (hints.candidate_ports or [8000])[:6]:
                        agent = http_adapter._discover_agent(f"http://localhost:{port}")
                        if agent:
                            for k in blank:
                                hints.extra_fields[k] = agent
                            # This port answered -> it's the live backend; try it first.
                            hints.candidate_ports = [port] + [p for p in hints.candidate_ports if p != port]
                            print(f"  discovered {blank} = {agent!r} from the live app (port {port}); trying it first")
                            break
                candidates = api_discovery.to_http_configs(hints)
                if candidates:
                    print(f"No config supplied; trying {len(candidates)} candidate(s) from api_hints.json ...")
                reachable = None                      # a correct endpoint that merely errored (app-side)
                for cand in candidates:
                    r = http_adapter.probe_endpoint(cand, "Connectivity check: please reply with the word OK.")
                    if r["kind"] == "ok":
                        http_config = cand
                        cfg_file.write_text(cand.model_dump_json(indent=2))
                        print(f"  auto-detected {cand.url} (field={cand.message_field}, reply_path={cand.reply_path}) "
                              f"-> wrote {cfg_file}")
                        break
                    # Endpoint exists but the app errored / needs auth / wrong shape: remember the best.
                    if reachable is None and r["kind"] in ("app_error", "auth", "bad_shape", "reachable_no_reply"):
                        reachable = (cand, r)
                # Last resort: network discovery against the hinted base URL.
                if http_config is None and hints.base_url:
                    report: list[str] = []
                    found = http_adapter.discover(hints.base_url, report=report)
                    if found:
                        http_config = found
                        cfg_file.write_text(found.model_dump_json(indent=2))
                        print(f"  auto-discovered {found.url} -> wrote {cfg_file}")
                # Found the right endpoint but the app itself isn't healthy -> save config, explain, stop.
                if http_config is None and reachable is not None:
                    cand, r = reachable
                    cfg_file.write_text(cand.model_dump_json(indent=2))
                    raise SystemExit(
                        f"Detected the API at {cand.url} (field={cand.message_field}, reply_path={cand.reply_path}) "
                        f"and saved {cfg_file.name},\n  but a connectivity check {r['detail']}\n"
                        + ("  The endpoint and request shape look right; the app's OWN backend returned the error "
                           "(e.g. its LLM/upstream is down or a key is missing). Fix the app, then re-run - no config "
                           "change needed." if r["kind"] == "app_error" else
                           "  Add the needed auth header(s) to \"headers\" in " + cfg_file.name + " and re-run."
                           if r["kind"] == "auth" else
                           "  Adjust extra_body/message_field in " + cfg_file.name + " to match the request shape."
                           if r["kind"] == "bad_shape" else
                           "  Set the correct reply_path in " + cfg_file.name + " (the reply wasn't where expected)."))

        if http_config is None and not report_agent._has_harness(args.target):
            raise SystemExit("auto-probe needs a running app: pass --http <url>, add sentinel.http.json, "
                             "or --discover <base-url> to auto-build one.\n"
                             "  `analyze` writes api_hints.json with its best guess at the port/endpoint/shape - "
                             "start the app so auto-detect can verify it, or edit sentinel.http.json. See RUNBOOK.md.")

        findings = _load(out, "findings.json", Finding)
        llm_findings = [f for f in findings if f.detector == "llm" and f.probe]
        if not llm_findings:
            raise SystemExit("No LLM-proposed weaknesses to probe. Run `analyze` with SENTINEL_LLM=anthropic first.")

        # Verify the endpoint works (reachable AND a usable reply) BEFORE probing.
        ok, detail, sample = autoprobe.preflight(args.target, args.backend, args.target_llm, http_config)
        if not ok:
            raise SystemExit(
                f"Endpoint check failed: {detail}\n"
                "  Fix the config (url, message_field, extra_body, reply_path) in sentinel.http.json,\n"
                "  or use --discover <base-url> to auto-build it. Common chat paths: /api/chat /chat /v1/chat/completions.")
        print(f"Endpoint OK. Sample reply: {sample!r}")

        risky = [f for f in llm_findings if autoprobe.is_write_risky(f)]
        if args.safe and risky:
            print(f"--safe: skipping {len(risky)} write-risky weakness(es); running {len(llm_findings) - len(risky)} read-only probe(s).")
        elif risky and http_config is not None:
            print(f"WARNING: {len(risky)} probe(s) could trigger REAL actions on a live app. Use --safe to skip them.")
        print(f"Probing {len(llm_findings)} LLM-proposed weakness(es)...")
        results, updated = autoprobe.run_autoprobes(findings, args.target, args.backend, args.target_llm,
                                                    http_config, safe=args.safe)
        _save(out / "findings.json", updated)
        _save(out / "probe_results.json", results)
        confirmed = sum(r.success for r in results)
        tool_hits = sum(1 for r in results if "TOOLS EXECUTED" in r.reason)
        print(f"Auto-probe: confirmed {confirmed}/{len(results)} weaknesses "
              f"({'via ' + http_config.url if http_config else 'run_case harness'}); "
              f"{tool_hits} probe(s) triggered real tool calls")
        for r in results:
            mark = "CONFIRMED" if r.success else ("skipped" if "skipped" in r.reason else "not confirmed")
            print(f"  {r.attack_id} family {r.check_family}: {mark} - {r.reason[:90]}")
    elif args.command == "report":
        _require_analyzed(args.target)
        rep = report_agent.build_report(args.target)
        s = rep["summary"]
        print(f"{s['structural_weaknesses']} structural weaknesses; "
              f"{s['worst_case_exploitable']} exploitable by a weak model -> runs/{args.target.name}/structural_report.md")
    elif args.command == "remediate":
        out = _require_analyzed(args.target)
        if not llm.enabled():
            raise SystemExit(
                "remediate needs a real model: set SENTINEL_LLM=anthropic (and ANTHROPIC_API_KEY).\n"
                "  It reads your actual findings, proposes a real fix per weakness, and writes a report\n"
                "  plus patches - it never modifies your code.")
        rep = remediate_agent.remediate(args.target, out)
        s = rep["summary"]
        print(f"Remediation: {s['selected']} finding(s) - {s['with_patch']} with a ready patch, "
              f"{s['described_only']} described-only, {s['needs_review']} need review "
              f"-> runs/{args.target.name}/remediation.md")
        for r in rep["remediations"]:
            tag = "patch" if (r["patch"] and r["compiles"]) else ("review" if r["problems"] else "described")
            print(f"  {r['finding_id']} family {r['family']} {r['file']}:{r['line']} [{tag}] conf={r['confidence']}")

    elif args.command == "scan":
        _require_target(args.target)
        out = analyze(args.target)
        if report_agent._has_harness(args.target):          # the bundled/wired target can be attacked offline
            attack(args.target, args.backend, args.target_llm, args.dump)
        report_agent.build_report(args.target)
        if llm.enabled():                                   # suggest real fixes for the real code
            rep = remediate_agent.remediate(args.target, out)
            s = rep["summary"]
            print(f"\nSENTINEL SCAN COMPLETE -> runs/{args.target.name}/ "
                  f"(structural_report.md; remediation.md: {s['with_patch']} ready patch(es), "
                  f"{s['needs_review']} to review)")
        else:
            print(f"\nSENTINEL SCAN COMPLETE -> runs/{args.target.name}/ (structural_report.md). "
                  f"Set SENTINEL_LLM=anthropic and run `remediate` for fix suggestions on the real code.")
    else:  # score: accuracy when an answer key exists, otherwise a posture grade
        out = _require_analyzed(args.target)
        answer_key = args.target / "answer_key.yaml"
        if answer_key.exists():
            findings = _load(out, "findings.json", Finding)
            print(json.dumps(score(findings, answer_key), indent=2))
        else:
            rep = posture(out)
            print(f"Security posture: grade {rep['grade']} (risk score {rep['risk_score']}/100) "
                  f"- {rep['note']}")
            bs = rep["weaknesses_by_severity"]
            print(f"  weaknesses: {bs['critical']} critical, {bs['high']} high, {bs['medium']} medium, {bs['low']} low")
            for w in rep["weaknesses"]:
                print(f"  - [{w['severity']}] {w['name']} x{w['finding_count']}  ({w['confidence']})")
            c = rep["coverage"]
            print(f"  coverage: {c['files']} files, {c['agents']} agents, {c['tools']} tools, {c['llm_calls']} LLM calls")
            print(json.dumps(rep, indent=2) if args.json else "")


if __name__ == "__main__":
    main()
