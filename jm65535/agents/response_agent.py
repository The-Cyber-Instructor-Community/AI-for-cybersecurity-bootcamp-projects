"""
Response Agent — runs when triage is malicious (>= threshold) or ambiguous.

Design (safety-first):
  - The LLM chooses WHICH actions to propose (from the editable response playbook);
    our code resolves the CONCRETE targets deterministically (persistence file,
    dropped payload path + hash, running PID) — the model never picks a path to
    delete, so it can't target the wrong thing.
  - Technique-aware targets: T1547.011 -> plist + its ProgramArguments payload;
    T1546.004 -> shell config + the script it references.
  - Evidence preserved BEFORE any destructive action (read-only copy, no approval).
  - Each state-changing action approved INDIVIDUALLY and run in a safe order.
  - The execution layer enforces hard guards regardless of what's approved.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from common import (CaseContext, compose_playbooks, claude_complete,
                    extract_json, RESPONSE_MODEL)
from tools import execution, slack_client, macos_tools

# Safe execution order; preserve_evidence always precedes these.
ACTION_ORDER = {"kill_process": 1, "remove_persistence_file": 2,
                "remove_config_persistence": 2, "quarantine_file": 3, "block_ip": 4}

SYSTEM_WRAPPER = (
    "You are the response agent in an automated macOS SOC. Given the triage "
    "verdict and the response playbook(s), choose WHICH response actions to "
    "propose. You do NOT choose targets (paths/PIDs are resolved for you) and you "
    "do NOT execute — a human approves each action. Output ONLY JSON: "
    '{"actions":[{"action":"<name>","rationale":"<one line, specific>"}]}.'
)

_SUSPICIOUS_PATH = re.compile(r'(/(?:tmp|private/tmp|var/tmp|Users/Shared)/[^\s"\';|&()]+)')


def _extract_shell_payload(config_path: str | None) -> str | None:
    """Find a script referenced from a suspicious location in a shell config."""
    if not config_path:
        return None
    try:
        content = Path(config_path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    m = _SUSPICIOUS_PATH.search(content)
    return m.group(1) if m else None


def _resolve_targets(case: CaseContext) -> dict:
    """Deterministically resolve the concrete targets from the alert + endpoint."""
    file_path = case.file_path
    kf = (case.triage or {}).get("key_findings", {}) or {}
    tg = {"plist_path": None, "config_path": None, "payload_path": None,
          "payload_sha256": None, "pid": None, "process": None, "ip": None, "marker": None}

    if "T1546.004" in case.techniques:                       # shell config modification
        tg["config_path"] = file_path
        payload = kf.get("payload") if isinstance(kf.get("payload"), str) else None
        if not payload or not payload.startswith("/"):
            payload = _extract_shell_payload(file_path)
        tg["payload_path"] = payload
        tg["marker"] = payload                               # remove config lines referencing it
    elif file_path and file_path.endswith(".plist"):         # LaunchAgent/Daemon
        tg["plist_path"] = file_path
        info = macos_tools.read_plist(file_path)
        tg["payload_path"] = execution.resolve_payload(info.get("program_arguments") or [])

    pp = tg["payload_path"]
    if pp and Path(pp).is_file():
        tg["payload_sha256"] = macos_tools.sha256_file(pp).get("sha256")
        proc = macos_tools.get_process_info(Path(pp).name)
        if proc.get("running"):
            tg["pid"], tg["process"] = proc.get("pid"), proc.get("comm")
    return tg


def _describe(action: str, tg: dict) -> str | None:
    """Human/Slack-facing target description; None means 'skip — no valid target'."""
    if action == "kill_process":
        return f"PID {tg['pid']} ({tg.get('process') or '?'})" if tg.get("pid") else None
    if action == "remove_persistence_file":
        return tg["plist_path"] if tg.get("plist_path") else None
    if action == "remove_config_persistence":
        return (f"{tg['config_path']} (remove line(s) referencing {tg.get('marker')})"
                if tg.get("config_path") and tg.get("marker") else None)
    if action == "quarantine_file":
        sha = (tg.get("payload_sha256") or "")[:12]
        return f"{tg['payload_path']} (sha256 {sha})" if tg.get("payload_path") else None
    if action == "block_ip":
        return tg["ip"] if tg.get("ip") else None
    return action  # read-only / escalation actions


def respond(case: CaseContext, *, approval_mode: str = "prompt", execute: bool = False) -> CaseContext:
    if not case.triage or not case.triage.get("actionable"):
        case.response = {"proposed_actions": [], "note": "triage not actionable — no response"}
        return case
    playbooks = compose_playbooks(case.techniques, "response")
    if not playbooks:
        case.response = {"proposed_actions": [], "note": "no response playbook"}
        return case

    targets = _resolve_targets(case)
    body = "\n\n".join(f"# RESPONSE PLAYBOOK — {p.technique}\n{p.body}" for p in playbooks)
    prompt = (
        f"Triage verdict:\n{json.dumps(case.triage, indent=2)}\n\n"
        f"Resolved targets (do not change these):\n{json.dumps(targets, indent=2)}\n\n"
        "Choose which response actions to propose (only those whose target exists)."
    )
    proposal = extract_json(claude_complete(model=RESPONSE_MODEL,
                                            system=f"{SYSTEM_WRAPPER}\n\n{body}", prompt=prompt))
    proposed = proposal.get("actions", []) or []

    items = []
    for a in proposed:
        name = a.get("action")
        desc = _describe(name, targets)
        if desc is None and name in ACTION_ORDER:
            continue  # no valid target — skip
        items.append({"action": name, "target_desc": desc,
                      "rationale": a.get("rationale", ""), "approved": None, "result": None})
    items.sort(key=lambda i: ACTION_ORDER.get(i["action"], 9))

    # --- evidence-first (no approval; read-only) ---
    destructive = [i for i in items if i["action"] in ACTION_ORDER]
    evidence = None
    if destructive:
        artifacts = [p for p in (targets["plist_path"], targets["config_path"],
                                 targets["payload_path"]) if p]
        evidence = execution.preserve_evidence(case.case_id, artifacts, dry_run=not execute)

    # --- per-action approval + execution in safe order ---
    tg_exec = {"pid": targets["pid"], "plist_path": targets["plist_path"],
               "config_path": targets["config_path"], "marker": targets["marker"],
               "file_path": targets["payload_path"], "payload_path": targets["payload_path"],
               "ip": targets["ip"]}
    for it in items:
        if it["action"] not in ACTION_ORDER:      # escalate / no_action etc.
            it["approved"], it["result"] = True, {"note": "informational action"}
            continue
        appr = slack_client.request_action_approval(
            action=it["action"], target_desc=it["target_desc"],
            rationale=it["rationale"], case_id=case.case_id,
            techniques=case.techniques, mode=approval_mode)
        it["approved"], it["approver"] = appr["approved"], appr["approver"]
        it["result"] = (execution.execute_action(it["action"], tg_exec, dry_run=not execute)
                        if appr["approved"] else {"skipped": True, "reason": "analyst rejected"})

    case.response = {
        "proposed_actions": [i["action"] for i in items],
        "targets": targets, "evidence": evidence, "items": items, "dry_run": not execute,
    }
    return case
