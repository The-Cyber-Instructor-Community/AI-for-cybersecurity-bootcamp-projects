---
playbook: response
technique: T1059.002
name: AppleScript (osascript) Execution — Response
responses:
  collect_forensics:  { executor: ssh,        approval: none,  read_only: true }
  kill_process:       { executor: custom_ar,  approval: slack, script: kill-process }
  quarantine_file:    { executor: custom_ar,  approval: slack, script: quarantine-file }
  block_ip:           { executor: default_ar, approval: slack, script: firewall-drop }
  escalate_to_slack:  { executor: slack,       approval: none }
  no_action:          { executor: none,        approval: none }
---

# Response — AppleScript / osascript Execution (T1059.002)

You receive the triage verdict + findings. Propose response actions; the
orchestrator gates execution on Slack approval. **You recommend; the analyst
approves.** `collect_forensics` is read-only; every state-changing action is
Slack-gated.

> Prefer whatever action I approved for similar past cases (retrieved via RAG).

## Choose actions by verdict (edit to change behavior)

- **malicious (confidence ≥ threshold):**
  - `kill_process` — terminate the osascript process (and children) if still running.
  - `quarantine_file` — isolate any downloaded/dropped payload identified in triage.
  - `block_ip` — only if enrichment found a concrete external IP contacted.
  - Post as one Slack approval with the script behavior + findings.

- **ambiguous:** `escalate_to_slack` with findings; don't auto-propose destructive actions.

- **benign:** `no_action` (Notes agent still records it).

## Rules

- osascript itself often exits quickly — check whether the process (or a spawned
  child) is still alive before proposing `kill_process`; if gone, focus on
  `quarantine_file` / `block_ip` and forensics.
- Never propose `block_ip` without a concrete IP from enrichment.
- Note: **there is no `remove_persistence_file` here** — execution isn't
  persistence. If this alert is part of a D4 correlation, the persistence removal
  comes from the T1547.011 response playbook (composed).

## Output

```json
{
  "proposed_actions": ["kill_process", "quarantine_file"],
  "targets": { "pid": 0, "file_path": "...", "ip": null },
  "slack_summary": "one-paragraph analyst-facing rationale",
  "requires_approval": true
}
```
