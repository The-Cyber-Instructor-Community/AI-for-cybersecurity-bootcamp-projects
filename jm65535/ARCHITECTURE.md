# Architecture

Living document — updated as each piece is built. Current state: detection rules
deployed + validated (T1547.011), agentic playbooks written, and the
triage/response/notes pipeline built + validated end-to-end (demo runs on the host
Mac). Next: dataset + RAG.

**Detection & response design** — how the two techniques are detected, enriched,
scored, and responded to (detections D1–D5, the persistence→execution correlation
rule, `collect_forensics` enrichment, confidence scoring, and the AR/custom/SSH
execution routing) lives in [docs/DETECTION_RESPONSE_DESIGN.md](docs/DETECTION_RESPONSE_DESIGN.md).

## Models — three distinct roles

Don't conflate the **reasoning LLM** with the **embedding model** — they do
completely different jobs.

**Reasoning / decision LLMs (Claude):**
- **Triage Agent**: Claude Sonnet — the reasoning-heavy step (weighing tool
  results + retrieved RAG examples against the playbook's decision criteria).
- **Response Agent / Notes Agent**: Claude Haiku — cheaper, high-volume,
  low-judgment formatting/selection tasks.

**Embedding model (RAG retrieval): `all-MiniLM-L6-v2`** — turns text into vectors
for similarity search *only*; it does **not** reason or make decisions. Runs
locally via onnxruntime (no PyTorch, no API cost). Chroma uses it to find the most
similar labeled past cases, which are then fed to the triage LLM.

**Stretch comparison LLM: `Foundation-Sec-8B`** — an open-source *reasoning* model
that swaps in for **Claude's decision role** (not the embedding role). LoRA
fine-tuned on the generated dataset, run via Ollama, and compared against the
Claude+RAG baseline. Not in the live pipeline by default.

## Agent communication

No agent-to-agent conversation. The orchestrator holds a single structured
`CaseContext` object per alert (alert → triage verdict/findings → response
action/approval → final note) and passes it as a plain object between
function calls. Every Claude API call is stateless — it receives the relevant
slice of `CaseContext` as input, nothing relies on multi-turn chat memory.
The Notes Agent persists the full accumulated context to disk on every run,
so a mid-pipeline failure doesn't silently lose anything.

## Deployment architecture (target: decoupled brain)

The demo runs the agent pipeline **on the monitored endpoint** — the host Mac is
both the Wazuh agent *and* the "SOC brain" — for simplicity. That conflation does
not generalize: in production you don't control endpoints, can't host an LLM on
them, and must not ship API keys / response logic to every monitored machine (an
attacker who owns the endpoint would then own your SOC automation too). The target
architecture decouples three roles:

```
Endpoint (Wazuh agent)      Wazuh manager + indexer      SOC-Copilot service (brain)
 - collects telemetry   →    - detection rules       →    - reads alerts (Wazuh API)
 - runs AR scripts      ←    - alert store           ←    - reasons with LLM (cloud
   (enrich + respond)         - manager→agent channel        API default / Ollama)
 (dumb, no secrets)          (SIEM)                         - dispatches via Wazuh AR
                                                            (holds the key; runs anywhere)
```

- **Brain is a standalone service**, not pinned to the endpoint or the manager. It
  can co-locate with the manager (simplest, one compose file) or run on a separate
  host — it just points at Wazuh over the API.
- **LLM is pluggable config, not a location problem** — cloud API (default, lowest
  friction) or a local Ollama (air-gapped/private). "The server has no LLM" is not
  a blocker; the brain calls the configured endpoint.
- **Endpoint access is abstracted** behind an `EndpointAccess` interface so the
  *same* agents run in either topology:
  - `LocalEndpoint` — subprocess (current demo; brain == endpoint).
  - `WazuhAREndpoint` — via Wazuh Active Response + manager API (production path;
    scales to N endpoints over the existing secure channel).
  - `SSHEndpoint` — optional adapter for servers you already administer; **not** the
    primary mechanism (SSH-to-every-endpoint doesn't scale and widens attack surface).
- **Enrichment prefers alert-carried data first** (the FIM alert already includes
  the file `sha256`, so VT/history need no endpoint touch), then AR scripts /
  osquery for endpoint-local facts (signing, live process).

Status: documented target; `LocalEndpoint` implemented (demo). The interface
refactor + `WazuhAREndpoint` are a **stretch goal** (future work).

## Security

- Wazuh dashboard, indexer API, and agent ports are restricted by cloud
  firewall to an admin-IP allow-list — nothing is open to `0.0.0.0/0`
  (see `infra/README.md`).
- SSH is key-only; password auth and root login are disabled at the OS level.
- Slack integration uses Bolt Socket Mode — an outbound websocket, so there's
  no public webhook endpoint to expose or harden.
- Secrets are never stored in plaintext: `.env` holds only 1Password
  `op://` references, resolved at runtime via `op run` (see `docs/SETUP.md`).

## Known limitation: plaintext credentials in docker-compose.yml

The wazuh-docker single-node deployment model (not something introduced by
this project) requires `INDEXER_PASSWORD`/`DASHBOARD_PASSWORD` as plaintext
environment variables in `docker-compose.yml`, since the manager and
dashboard containers authenticate to the indexer with them at runtime.
`docker inspect`/`docker exec ... env` will also show them in plaintext to
anyone who can run docker commands on the host.

This is an accepted, bounded risk: docker group membership is effectively
root-equivalent, so the real access boundary is SSH to the VM, not the
network — and SSH is already key-only and restricted to an admin-IP allowlist
by the Terraform firewall. A production multi-tenant deployment would want
Docker secrets or a vault-backed injection method instead; wazuh-docker's
images don't support that out of the box, so it wasn't built here. Worth
knowing before assuming every credential in this system is handled the same
way `.env`/1Password secrets are for the Python pipeline.

Mitigations in place: default demo credentials (`admin`/`SecretPassword`,
`kibanaserver`/`kibanaserver`, plus four unused demo accounts —
`kibanaro`, `logstash`, `readall`, `snapshotrestore`) are rotated/removed
immediately after first deploy — see `scripts/harden-wazuh.sh`. File
permissions on `docker-compose.yml` are restricted (`chmod 600`) as
defense in depth, though this doesn't change the `docker inspect` exposure.

## Playbook-as-config (agentic playbooks)

Analyst changes agent behavior by editing Markdown instruction files, not code.
Each technique is split into an editable **triage** and **response** playbook
(`playbooks/<technique>/{triage,response}.md`): natural-language instructions the
agent reads and reasons over, plus YAML frontmatter for the machine bits (tools,
`confidence_threshold`, action→executor mapping). The orchestrator selects
playbooks by the alert's MITRE technique(s) and the agent composes across them for
multi-technique alerts. RAG (retrieved labeled past cases) layers on top as the
primary "learning" mechanism. Full design: `docs/DETECTION_RESPONSE_DESIGN.md`.
