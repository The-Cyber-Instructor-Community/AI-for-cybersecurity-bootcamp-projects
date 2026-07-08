---
playbook: response
technique: T1547.011
name: LaunchAgent / LaunchDaemon Persistence — Response
# action -> how it executes. approval:slack means an analyst MUST approve first.
responses:
  collect_forensics:        { executor: ssh,        approval: none,  read_only: true }
  remove_persistence_file:  { executor: custom_ar,  approval: slack, script: remove-plist }
  kill_process:             { executor: custom_ar,  approval: slack, script: kill-process }
  quarantine_file:          { executor: custom_ar,  approval: slack, script: quarantine-file }
  block_ip:                 { executor: default_ar, approval: slack, script: firewall-drop }
  escalate_to_slack:        { executor: slack,       approval: none }
  no_action:                { executor: none,        approval: none }
---

# Response — LaunchAgent / LaunchDaemon Persistence (T1547.011)

You choose **which** actions to propose. You do **not** choose targets — the exact
plist path, dropped-payload path + hash, and running PID are resolved for you and
given in the prompt. You never execute; the analyst approves **each action
individually**, and evidence is preserved before anything destructive runs.

> Weight the retrieved past cases: if I approved a specific action for a similar
> alert before, prefer that action.

## Choose actions by verdict (edit to change behavior)

- **malicious (confidence ≥ threshold):** propose the applicable subset —
  - `kill_process` — **only if a running PID was resolved** (kills that process
    instance; the interpreter binary is never touched).
  - `remove_persistence_file` — removes the offending **plist** (stops re-execution).
  - `quarantine_file` — **only if a dropped payload path was resolved**; isolates
    the dropped script, never the interpreter (`osascript`/`sh`).
  - `block_ip` — **only if enrichment resolved a concrete external IP.**
- **ambiguous:** `escalate_to_slack` — do not propose destructive actions.
- **benign:** `no_action`.

## Rules (safety-first)

- **Evidence before remediation:** the plist + dropped payload are copied to the
  evidence store (with hashes) automatically before any destructive action — you
  don't need to request it.
- **Precision:** kill the resolved **PID**, remove the **plist**, quarantine the
  **dropped payload** — never the interpreter (`/usr/bin/osascript`, `/bin/sh`).
  The execution layer hard-refuses system/interpreter paths regardless.
- **Only propose an action if its target was resolved** (no PID → don't propose
  `kill_process`; no payload path → don't propose `quarantine_file`).
- **Order:** kill → remove → quarantine → block (handled by the orchestrator).
- **LaunchDaemon (root scope) is higher stakes** — say so in the rationale.

## Output

Propose only the actions; targets are attached for you. Per-action rationale is
what the analyst sees at approval time.

```json
{ "actions": [
    { "action": "kill_process",            "rationale": "one line, specific to the resolved target" },
    { "action": "remove_persistence_file", "rationale": "..." }
] }
```
