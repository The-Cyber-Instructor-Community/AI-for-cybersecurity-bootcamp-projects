"""
Orchestrator — the sequential pipeline that ties the agents together.

Per alert: build a CaseContext, run Triage, run Response iff triage is actionable,
then always run Notes. Holds the single CaseContext object and passes it between
agents (no agent-to-agent chat). Playbook selection is by MITRE technique
(common.techniques_for_alert), so multi-technique alerts compose automatically.

Run (secrets injected by 1Password):
    op run --env-file=.env -- .venv/bin/python orchestrator.py \
        --alert data/sample_alerts/d1_launchagent.json --approval prompt
"""

from __future__ import annotations

import argparse
import json
import time

from common import CaseContext, techniques_for_alert, CASES_DIR, PROJECT_ROOT, ui_report
from agents.triage_agent import triage
from agents.response_agent import respond
from agents.notes_agent import write_note

_WATCH_STATE = PROJECT_ROOT / ".aisoc_watch_seen.json"


def process_alert(alert: dict, *, approval_mode: str, execute: bool) -> CaseContext:
    case = CaseContext(alert=alert, techniques=techniques_for_alert(alert))
    print(f"\n{'='*70}\nCASE {case.case_id} | rule {case.rule_id} | techniques {case.techniques}")
    print(f"  {case.rule_description}\n{'='*70}")
    ui_report("alert", {"case_id": case.case_id, "rule_id": case.rule_id,
                        "alert_id": case.alert.get("id"), "file_path": case.file_path,
                        "timestamp": case.alert.get("timestamp"),
                        "description": case.rule_description, "techniques": case.techniques,
                        "agent": case.agent_name})

    print(">> Triage agent...")
    case = triage(case)
    t = case.triage
    print(f"   verdict={t.get('verdict')} confidence={t.get('confidence')} "
          f"actionable={t.get('actionable')}  ({len(case.enrichment.get('tool_trace', []))} tool calls)")
    ui_report("triage", {"case_id": case.case_id, "verdict": t.get("verdict"),
                         "confidence": t.get("confidence"), "actionable": t.get("actionable"),
                         "tool_calls": len(case.enrichment.get("tool_trace", [])),
                         "rag": t.get("rag_count", 0)})

    if t.get("actionable"):
        print(">> Response agent...")
        case = respond(case, approval_mode=approval_mode, execute=execute)
        r = case.response
        approved = [i["action"] for i in r.get("items", []) if i.get("approved")]
        print(f"   proposed={r.get('proposed_actions')} approved={approved} "
              f"evidence={'preserved' if r.get('evidence') else 'none'} dry_run={r.get('dry_run')}")
        ui_report("response", {"case_id": case.case_id,
                               "items": [{"action": i["action"], "target_desc": i.get("target_desc"),
                                          "approved": i.get("approved")} for i in r.get("items", [])],
                               "evidence": bool(r.get("evidence")), "dry_run": r.get("dry_run")})
    else:
        print(">> Response agent skipped (not actionable).")
        case = respond(case)  # records the no-response note

    print(">> Notes agent...")
    case = write_note(case)
    print(f"   case note -> {case.note_path}")
    ui_report("note", {"case_id": case.case_id, "note_path": case.note_path,
                       "verdict": t.get("verdict")})

    # Persist the full CaseContext for audit / dataset seeding.
    CASES_DIR.mkdir(exist_ok=True)
    (CASES_DIR / f"{case.created_at[:10]}_{case.case_id}.json").write_text(
        json.dumps(case.to_dict(), indent=2), encoding="utf-8")
    return case


# --------------------------------------------------------------------------- #
# Watch mode — always-on: poll Wazuh for NEW alerts, auto-run the pipeline.
# This is what makes it a hands-off framework: real detection fires -> watcher
# pulls it within the poll interval -> triage -> Slack approval -> response.
# --------------------------------------------------------------------------- #

def _alert_key(a: dict) -> str:
    return (a.get("id") or f"{a.get('rule', {}).get('id')}-{a.get('timestamp')}-"
            f"{a.get('syscheck', {}).get('path', '')}")


def _load_seen() -> set:
    try:
        return set(json.loads(_WATCH_STATE.read_text()))
    except Exception:
        return set()


def _save_seen(seen: set) -> None:
    try:
        _WATCH_STATE.write_text(json.dumps(list(seen)[-500:]))  # bounded
    except Exception:
        pass


def watch(*, poll_interval: int, approval_mode: str, execute: bool) -> None:
    from tools.wazuh_client import fetch_recent_alerts
    seen = _load_seen()
    print(f"[watch] polling Wazuh every {poll_interval}s for new ai_soc_copilot alerts "
          f"(approval={approval_mode}, execute={execute}). Ctrl-C to stop.", flush=True)
    while True:
        try:
            alerts = fetch_recent_alerts(rule_groups=["ai_soc_copilot"], min_level=5, size=30)
            new = [a for a in alerts if _alert_key(a) not in seen]
            new.reverse()  # oldest-first
            for a in new:
                process_alert(a, approval_mode=approval_mode, execute=execute)
                seen.add(_alert_key(a))
                _save_seen(seen)
            if not new:
                print(".", end="", flush=True)
            time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\n[watch] stopped.", flush=True)
            return
        except Exception as exc:  # keep watching through transient indexer/tunnel errors
            print(f"\n[watch] error: {exc} — retrying in {poll_interval}s", flush=True)
            time.sleep(poll_interval)


def main() -> None:
    ap = argparse.ArgumentParser(description="AI-SOC-Copilot orchestrator")
    ap.add_argument("--alert", default="data/sample_alerts/d1_launchagent.json",
                    help="path to a Wazuh alert JSON to process")
    ap.add_argument("--live", action="store_true",
                    help="fetch recent alerts from the Wazuh indexer instead of --alert")
    ap.add_argument("--watch", action="store_true",
                    help="always-on: poll Wazuh and auto-process each NEW alert")
    ap.add_argument("--poll-interval", type=int, default=20,
                    help="seconds between polls in --watch mode (default 20)")
    ap.add_argument("--approval", choices=["auto", "prompt", "slack"], default="prompt")
    ap.add_argument("--execute", action="store_true",
                    help="actually execute approved actions (default: dry-run)")
    args = ap.parse_args()

    if args.watch:
        watch(poll_interval=args.poll_interval, approval_mode=args.approval, execute=args.execute)
        return

    if args.live:
        from tools.wazuh_client import fetch_recent_alerts
        alerts = fetch_recent_alerts(rule_groups=["ai_soc_copilot"], min_level=5)
        print(f"fetched {len(alerts)} alert(s) from the indexer")
    else:
        alerts = [json.load(open(args.alert))]

    for alert in alerts:
        process_alert(alert, approval_mode=args.approval, execute=args.execute)


if __name__ == "__main__":
    main()
