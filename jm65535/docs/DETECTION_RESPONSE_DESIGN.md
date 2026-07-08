# Detection & Response Design

How the two in-scope techniques are detected, enriched, scored, and responded to.
This is the blueprint the manager rules (`config/wazuh_cluster/local_rules.xml`),
the triage/enrichment agents, and the response agent all implement.

Scope (unchanged from the project plan):
- **T1547.011** — LaunchAgent / LaunchDaemon persistence
- **T1059.002** — AppleScript (osascript) execution

---

## Philosophy: detect lean → enrich deep → respond gated

| Stage | Where | Approval? | Job |
|-------|-------|-----------|-----|
| **Detect** | Wazuh manager rules | n/a | Fire on *observable* signals only — file path, process, and cross-event correlation. No content parsing in rules. |
| **Enrich** (`collect_forensics`) | enrichment/triage agent | **none** (read-only) | Gather the facts a rule can't see: code-signing, dropped-file hashes + VirusTotal, parent process, network egress, host history. |
| **Score** | triage agent (Claude) | n/a | Synthesize enrichment into a confidence score + rationale → malicious / ambiguous / benign. |
| **Respond** | response agent | **Slack approval (all state-changing actions)** | Propose an action only if confidence ≥ threshold; execute only after an analyst approves. |

Rationale: keeping content analysis out of the rules keeps detection fast and
avoids duplicating the agent's work; it also gives the enrichment agent something
substantive to do. Nothing that changes endpoint/network state runs without a
human approving it in Slack.

---

## Detections (D1–D5)

| # | Detection | Rule id(s) | Sev | Technique | Proposed response (after enrich + approval) |
|---|-----------|-----------|-----|-----------|---------------------------------------------|
| **D1** | LaunchAgent plist added/modified — **user/login scope** (`~/Library/LaunchAgents`, `/Library/LaunchAgents`) | 100010 / 100011 | med | T1547.011 | `collect_forensics` → `remove_persistence_file` |
| **D2** | LaunchDaemon added/modified — **system/root scope** (`/Library/LaunchDaemons`) | 100013 | high | T1547.011 | `collect_forensics` → `remove_persistence_file` |
| **D3** | osascript execution | 100020 / 100021 | low→med | T1059.002 | `collect_forensics`, escalate |
| **D4** | **Correlated**: persistence drop *then* osascript on the same host within a window | 100030 | **critical** | T1547.011→T1059.002 | `kill_process` + `remove_persistence_file` + `collect_forensics` |
| **D5** | Enrichment finds the spawned process reaching an external IP | (post-enrich, no rule) | — | — | `firewall-drop` / `route-null` that IP |

(D1 also has a low-severity *delete* rule, 100012, for completeness/audit.)

### Why the split matters
- **D1 vs D2** — a LaunchDaemon runs as **root at boot**; a user LaunchAgent runs
  in the login session. Same technique, materially different blast radius, so
  different base severity. This is derivable from the **path alone** (no content).
- **D3 alone is noisy** (osascript is heavily used by legitimate automation) and
  **D1 alone is ambiguous** (installers drop LaunchAgents constantly). **D4** —
  persistence *then* execution on the same host — is the high-confidence chain
  that justifies aggressive containment.

---

## Detection chaining (how D4 works)

Wazuh supports two chaining mechanisms; we use both.

1. **Single-event refinement — `<if_sid>`**: a child rule evaluated on the *same*
   event as its parent. Used for the FIM severity tiering (D1/D2 are children of
   Wazuh FIM rules 554/550/553).
2. **Cross-event correlation — `<if_matched_sid>` + `<timeframe>` + `<same_field>`**:
   fires when events co-occur within a window on the same host. D4 (rule 100030)
   triggers on an osascript event **if** a persistence event matched recently on
   the **same agent**.

### ⚠️ macOS FIM timing caveat
macOS FIM is **scheduled, not real-time** (up to a 5-minute scan delay — see
`config/wazuh_agent/macos_monitoring.conf.template`). So the plist-add alert can
arrive *after* the osascript alert, inverting the expected order. D4 therefore
correlates on **co-occurrence within a wide window** (≈10 min), not strict
ordering, and the exact correlation key (`same_field agent.id` vs `same_location`)
and the `if_sid`/`if_matched_sid` combination **must be validated with
`wazuh-logtest` on the manager** — cross-event correlation can't be verified from
the repo alone.

---

## Enrichment — `collect_forensics` (read-only, no approval)

Runs on every actionable alert to produce the facts scoring needs:

- **Code signature** of the referenced/executing binary — `codesign`/`spctl`:
  Apple-signed / known-developer / unsigned / ad-hoc.
- **Dropped files**: parse the plist's `ProgramArguments` (or the osascript body)
  → resolve referenced binaries/scripts → **SHA-256** each.
- **Reputation**: **VirusTotal lookup by hash only** (never upload the file).
  Verdict feeds the score. *Unknown to VT ≠ benign* — it's scored as inconclusive.
- **Parent process** of the plist writer / osascript invoker (signed automation
  vs. shell/unknown).
- **Network egress** of the spawned process (feeds D5).
- **Host history**: has this LaunchAgent path / script hash been seen before on
  this host? (queried from the Wazuh indexer).

Tools: `tools/macos_tools.py` (signing, process, network), `tools/wazuh_client.py`
(history), a VirusTotal client, and **SSH for artifact extraction** on remote
endpoints (see routing below).

---

## Confidence scoring

The triage agent (Claude, structured tool-use) synthesizes the enrichment signals
into a **confidence score (0–100)** with a written rationale, mapping to the
playbook's verdicts:

| Signal | Pushes toward malicious | Pushes toward benign |
|--------|-------------------------|----------------------|
| Code signature | unsigned / ad-hoc | Apple / known developer |
| VirusTotal | detections > 0 | clean, well-known hash |
| Path | `/tmp`, `/Users/Shared`, hidden dirs | standard app-support paths |
| Parent process | shell / unknown | known installer / automation |
| Network egress | external / rare IP | none / known-good |
| Host history | first-seen | previously-approved benign |

- **≥ threshold (e.g. 70)** → propose containment (malicious).
- **40–69** → escalate as ambiguous ("first-seen, no network" case).
- **< 40** → note only, no action (benign).

The **threshold is a tunable in the playbook frontmatter**, so an analyst changes
aggressiveness by editing a file, not code (consistent with the playbook design).

---

## Playbooks & composition routing

Playbooks are **agentic and analyst-editable**: natural-language `.md` instructions
that the agent reads and reasons over, with a small YAML frontmatter for the
machine-usable bits (technique id, alert rules, tool list, threshold, and the
action→executor mapping). Per the instructor's guidance, each technique is **split
into a triage playbook and a response playbook**:

```
playbooks/
  T1547.011/{triage,response}.md
  T1059.002/{triage,response}.md
  _base/macos_investigation.md      # shared primitives — STRETCH, not required
```

**Selection is deterministic; synthesis is agentic** — this is how a multi-technique
alert (like D4) is handled:

- The orchestrator reads the alert's `rule.mitre.id[]` and loads the **matching**
  technique playbook(s). The LLM never guesses which playbook applies.
- **One technique** → one `triage.md`. **Multiple techniques** (D4 tags both
  T1547.011 and T1059.002; or several alerts on one host) → the triage agent
  receives **all** matching `triage.md` files and produces **one unified
  investigation**: overlapping steps done once, prioritized by severity. The
  response agent composes the matching `response.md` files the same way (e.g. D4 →
  `remove_persistence_file` from T1547.011 + `kill_process` from T1059.002).

This keeps **depth** (focused per-technique playbooks, per the instructor's "go
deep") *and* handles **multi-technique threats** (composition) without a shallow
catch-all playbook.

**RAG layers on top** — the primary "learning" mechanism (fine-tuning is the
stretch comparison). See the RAG section below for how it works.

---

## RAG — retrieval-augmented triage

RAG lets the triage LLM **mirror the analyst's prior decisions** on similar cases,
without fine-tuning. Two models with different jobs are involved: an **embedding
model** (`all-MiniLM-L6-v2`) for retrieval, and the **reasoning LLM** (Claude) for
the decision. RAG feeds Claude; it does not replace it.

**Two phases — indexing is one-time, retrieval is per-alert and cheap:**

1. **Index once (offline, `scripts/embed_dataset.py`):** each labeled case in
   `data/dataset.jsonl` is embedded by all-MiniLM-L6-v2 and stored in Chroma
   (vector + label metadata). The corpus is **not** re-embedded per alert.
2. **Retrieve per alert (`rag.py`, `retrieve_similar`):** the incoming alert
   becomes a short query, all-MiniLM embeds **just that query** (one small vector,
   local, free), Chroma returns the top-k (3) most similar labeled cases by cosine
   similarity, and **only those 3 snippets** are injected into the triage prompt —
   never the whole corpus.
3. **Generate:** Claude reasons over the alert + tool findings + those 3 retrieved
   examples, guided by the playbook.

**Why it's cheap:** per alert the only costs are one *local* query embedding (onnx,
no API, ~ms), one *local* vector search (Chroma, ~ms), and ~a few hundred extra
prompt tokens (the 3 snippets) on the one Claude call — a fraction of a cent.
Retrieval cost stays flat as the corpus grows (10k cases → still embed 1 query,
still inject top-3), which is why RAG scales where stuffing the whole knowledge
base into every prompt would not.

**Feedback loop:** approve/reject/edit decisions append to `feedback_log.jsonl` and
can be re-embedded, so the corpus keeps aligning to the analyst over time.

---

## Response model — all state-changing actions Slack-gated

`collect_forensics` is read-only investigation and runs **without** approval.
Every action that changes endpoint or network state is **proposed by the response
agent and executed only after an analyst clicks Approve in Slack.** No
auto-containment — even D4.

### Execution routing: AR-first → custom → SSH

| Action | Mechanism | Notes |
|--------|-----------|-------|
| Block C2 IP (D5) | **default AR** `firewall-drop` / `route-null` | macOS `firewall-drop` uses pf |
| Disable compromised account | **default AR** `disable-account` | if enrichment implicates an account |
| `kill_process` | **custom AR** | kill the osascript / spawned PID |
| `remove_persistence_file` | **custom AR** | delete the LaunchAgent/Daemon plist |
| `quarantine_file` | **custom AR** | move dropped binary to a quarantine dir |
| **Artifact extraction** (files, `~/.zsh_history`, unified-log excerpts) | **SSH** | pull evidence *back to the analyst* for a remote endpoint; local reads when the endpoint is this Mac |

Rule of thumb: **default AR** covers network/account containment; **custom AR**
covers endpoint mutation; **SSH** is for *extraction* (moving artifacts off the
endpoint), not mutation.

### Human-in-the-loop, not auto-AR
Wazuh AR *can* fire automatically on a rule match — we deliberately **do not**
wire `<active-response>` to auto-trigger. Instead the response agent invokes the
AR command **on demand after approval** via the Wazuh API (`PUT /active-response`)
or SSH. The rules only *detect and classify*.

---

## New dependencies this introduces

- **`VT_API_KEY`** — VirusTotal (free tier: 4 lookups/min). Added to the `op://`
  secrets model like the others (`op://ai-soc-copilot/virustotal/api_key`),
  resolved at runtime via `op run`.
- **Custom AR scripts** to write + deploy to the agent
  (`kill_process`, `remove_persistence_file`, `quarantine_file`) under
  `/var/ossec/active-response/bin/`, declared in the manager's `ossec.conf`.
- **osascript telemetry validation** — confirm osascript events actually flow and
  how they're decoded (only FIM was verified in Phase 1) before trusting D3/D4.

---

## Open items / validation checklist

- [ ] Validate D4 correlation (`if_matched_sid` + correlation key) with `wazuh-logtest`.
- [ ] Confirm osascript telemetry + decoded fields; tighten rules 100020/100021.
- [ ] Add `VT_API_KEY` to 1Password + `.env`.
- [ ] Write + deploy the three custom AR scripts.
- [ ] Decide the default confidence threshold; put it in the playbook YAML.
