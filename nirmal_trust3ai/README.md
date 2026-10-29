# Sentinel - a multi-agent security reviewer for AI applications

Sentinel reviews an AI application the way a security engineer would: it maps the
code, threat-models it, attacks **only** what the threat model and a static scan point
to, confirms the real weaknesses against the running app, and proposes fixes it then
re-tests. Every finding is tagged with **OWASP Top 10 for LLM Apps (2026)**, **OWASP
Top 10 for Agentic Apps (2026)**, and **MITRE ATLAS (v2026.09)**.

It was built as an AI Security Bootcamp capstone. It ships with a deliberately
vulnerable practice app so you can run the whole pipeline end-to-end with no setup and
no API key.

> **Ethics / scope:** Sentinel is a defensive tool. Only run it against applications you
> own or are authorized to test. The dynamic probes are security tests; the `--safe`
> flag (see below) exists precisely so you don't trigger real side effects on a live app.

---

## Why it's designed this way

A naive "throw every jailbreak at the model" scanner is expensive and mostly tests the
*model vendor*, not *your app*. Sentinel is built on three ideas:

1. **Threat-model-gated attacks.** Static recon + a rules-based threat model decide
   which attack families are even *possible* for this app. Only those attacks run, so
   token cost stays proportional to the app's real attack surface.
2. **Model-independent findings.** The report focuses on *structural* weaknesses -
   missing guardrails in code and design that hold regardless of how strong or weak the
   underlying model is - because a prompt-only defense that works on a big model breaks
   on a cheaper one.
3. **Self-configuring.** Point it at any repo; it statically discovers the app's HTTP
   chat API (port, endpoint, request/response shape) and verifies that against the
   running app before probing - so you rarely write any configuration by hand.

---

## Quick start (offline, no API key)

Needs Python 3.11 and [uv](https://docs.astral.sh/uv/) (or plain `venv`/`pip`).

```bash
# from the repo root after `git clone`
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
# (without uv: python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]")

python -m sentinel.cli scan targets/helpdeskbot    # the whole pipeline in one command
```

`scan` runs analyze -> report -> attack -> remediate against the bundled vulnerable app
and prints a security posture grade. Everything above runs **offline** with a free,
deterministic scripted "model" - no key, no network.

Run the stages individually:

```bash
python -m sentinel.cli analyze targets/helpdeskbot   # system map + threat model + static scan
python -m sentinel.cli report  targets/helpdeskbot   # model-independent structural weakness report
python -m sentinel.cli attack  targets/helpdeskbot   # run only the threat-selected attacks
SENTINEL_LLM=anthropic python -m sentinel.cli remediate targets/helpdeskbot  # LLM fix suggestions for the real code (no changes made)
python -m sentinel.cli score   targets/helpdeskbot   # accuracy vs the answer key (or posture grade)
```

Outputs are written to `runs/<app-name>/` (git-ignored).

### Run the tests

```bash
python -m pytest -q
```

The unit suite is fully offline. A handful of integration tests read `runs/helpdeskbot/`
and skip until you've run `analyze` once - run `scan targets/helpdeskbot` first and they
all execute.

---

## Using the real model

Copy the template and add your key (the `.env` file is git-ignored and must never be
committed):

```bash
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY, and LLM_BACKEND=anthropic
```

- `LLM_BACKEND=anthropic` makes the **practice app** use a real model.
- `SENTINEL_LLM=anthropic` turns on Sentinel's optional LLM stages: deeper code
  understanding (`recon_llm`), finding triage, threat re-rating, LLM-as-judge probing,
  and the dynamic auto-probe loop.

```bash
SENTINEL_LLM=anthropic python -m sentinel.cli analyze targets/helpdeskbot
```

### Suggesting fixes for real code - `remediate`

`fix` applies and auto-verifies a known set of controls on the bundled practice app. For **any**
codebase, use `remediate`: it reads your actual findings, opens the real faulty source, and asks a
model to propose a concrete fix anchored to each family's model-independent control - then validates
every suggestion **without touching your code**.

```bash
SENTINEL_LLM=anthropic python -m sentinel.cli analyze   /path/to/your/app
SENTINEL_LLM=anthropic python -m sentinel.cli remediate /path/to/your/app
```

For each confirmed or high-severity finding it writes:

- `runs/<app>/remediation.md` - diagnosis, the suggested patch as a diff, why it holds regardless of
  model strength, and concrete **verification steps**.
- `runs/<app>/suggested_fixes/<id>.patch` - a ready patch you review and apply yourself
  (`git apply ...`).

Every suggestion is validated non-destructively: the fix's anchors must exist in the real file and
the patched Python must still compile, or the suggestion is flagged for review and marked low
confidence. **`remediate` never modifies your code** - you stay in control.

---

## Reviewing a real web app (auto-discovery + safe probing)

Sentinel can review any chat-style HTTP app, not just the bundled target.

```bash
# 1. Static analysis also writes runs/<app>/api_hints.json (zero tokens, zero network):
#    its best guess at the app's port, chat endpoint, and request/response shape.
SENTINEL_LLM=anthropic python -m sentinel.cli analyze /path/to/your/app

# 2. Start your app, then let autoprobe configure itself and confirm weaknesses:
SENTINEL_LLM=anthropic python -m sentinel.cli autoprobe /path/to/your/app --safe
```

What `autoprobe` does automatically:

- Reads `api_hints.json`, builds candidate endpoint configs, and **verifies** each one
  against the running app before probing (it classifies the response - reachable, auth
  required, wrong shape, or the app's own backend erroring - instead of failing blind).
- Writes a ready `sentinel.http.json` for the config that works, so the next run needs
  no setup.
- **`--safe`** skips every *write-risky* probe (anything that could trigger a real
  action - refunds, sends, deletes, tool calls with side effects) and flags any probe
  that still causes a real tool call. Always start with `--safe` on an app wired to real
  systems; drop it only when you accept real side effects.

If auto-detection can't reach your app, you can point it directly or hand it a config:

```bash
python -m sentinel.cli autoprobe /path/to/app --http http://localhost:8000/api/chat
# or create /path/to/app/sentinel.http.json (see docs/ARCHITECTURE.md for the schema)
```

---

## The bundled practice app

**`targets/helpdeskbot/`** - a multi-agent (orchestrator + Researcher + Emailer) help desk bot
with three mock tools and **five deliberately planted flaws** kept in `answer_key.yaml` (never
shown to Sentinel). This is the scoring target: `score` measures Sentinel's recall/precision
against that key. To review your own web app instead, point Sentinel at it and use the HTTP
auto-discovery described above.

---

## The six check families

Every rule, attack, and finding is organized by family, each mapped to the frameworks in
`sentinel/kb/families.yaml`:

| # | Family | OWASP | 
|---|--------|-------|
| 1 | Direct prompt injection | LLM01, ASI01 |
| 2 | Indirect prompt injection (via tools / RAG) | LLM01, LLM09 |
| 3 | Excessive agency | LLM03, ASI02 |
| 5 | Improper output handling | LLM10, ASI02 |
| 6 | Hidden context / secret leakage | LLM08, LLM02 |
| 7 | Insecure agent-to-agent communication | ASI07, ASI08 |

---

## Layout

```
sentinel/
  cli.py                  the subcommands: analyze attack probe autoprobe report remediate scan score
  models.py               Finding, Threat, Attack, AttackResult (shared by all agents)
  llm.py                  guarded LLM call: untrusted-code tags, JSON schema, token budget
  score.py                recall/precision vs an answer key, or a posture grade for a real app
  kb/                     OWASP LLM 2026, OWASP Agentic 2026, ATLAS subset, families + controls
  checks/rules/core.yaml  Semgrep rules, one or two per family
  agents/
    recon.py              ast -> system_map.json (no LLM)
    recon_llm.py          optional LLM code understanding (reducer-fed, chunked)
    threat_model.py       rules -> ranked ATLAS paths + data-flow diagram (optional LLM re-rating)
    static_scan.py        Semgrep -> findings (+ optional LLM triage)
    redteam.py            select only threat-matched attacks, then run them
    report.py             model-independent structural weakness report
    remediate.py          LLM-driven fix suggestions for the real code (never modifies it)
    autoprobe.py          turn LLM-proposed weaknesses into live probes, judge, confirm
    api_discovery.py      static discovery of a web app's chat API shape (zero tokens)
  harness/
    sandbox.py            run one target case in isolation (subprocess or Docker)
    oracles.py            plain-code pass/fail checks + LLM-as-judge
    http_adapter.py       talk to a running web app; verify/classify/discover its endpoint
  reducer/                type-aware source reducers (python / html / javascript)
  attacks/corpus.yaml     labelled probes against the practice app, tagged by family
targets/helpdeskbot/      the deliberately vulnerable practice app (+ answer_key.yaml)
docs/ARCHITECTURE.md      how the whole thing fits together
tests/                    unit + integration tests
```

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the full design.

## License

Licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) - see `LICENSE`.
Free to share and adapt for non-commercial use with attribution; derivatives must keep the same license.
