# Running Sentinel on a real-world app

Sentinel has two layers. Know which one applies to an app you didn't build:

| Capability | Works on any Python repo? | Why |
| --- | --- | --- |
| `analyze` (recon + threat model + static scan) | **Yes** | Reads code with `ast` + Semgrep; no app-specific wiring |
| `report` (structural weaknesses + controls) | **Yes** (static-only) | Maps findings to model-independent controls |
| `attack` / `fix` (dynamic red-team + verify) | **No, needs wiring** | Needs an entry point to run the app and a fix recipe |

The **static** layer is the model-independent core and runs on anything. The **dynamic**
layer needs a small harness per target (see the end).

## 1. Point Sentinel at the app (static analysis - works out of the box)

```bash
cd ~/Claude/Projects/AISecurityBootcampCapstone
source .venv/bin/activate

# Any local Python LLM/agent repo:
python -m sentinel.cli analyze /path/to/their-agent-app
python -m sentinel.cli report  /path/to/their-agent-app     # static-only report (auto-detected)

# Read the results:
#   runs/<appname>/threat_model.md       data-flow diagram + ranked ATLAS attack paths
#   runs/<appname>/structural_report.md  missing controls, per weakness, with the code fix
#   runs/<appname>/findings.json         every static hit (OWASP/ATLAS tagged)
#   runs/<appname>/system_map.json       the map Recon built
```

### LLM-assisted structure understanding (for unfamiliar app styles)

The `ast` + rule layer only knows patterns we taught it. With `SENTINEL_LLM=anthropic`, `analyze`
ALSO hands the source to an LLM that maps the app whatever its style and proposes weaknesses +
probes. Its findings are merged in (tagged `detector: "llm"`, de-duped against the rules) and the
map is written to `runs/<app>/app_understanding.json`.

```bash
SENTINEL_LLM=anthropic python -m sentinel.cli analyze /path/to/their-agent-app
```

This is the most reliable way to handle an app written very differently from the samples: the LLM
reads the real structure; the rules stay as a free, deterministic baseline. (Guarded: source is
wrapped as untrusted, the reply must match a schema, and a token budget caps the call.)

**Source reducer (how big repos fit).** Before sending code to the LLM, Sentinel reduces each file
by type (`sentinel/reducer/`): Python keeps imports, signatures, decorators, constants and
security-relevant function bodies while eliding the rest (`...`); HTML keeps `<script>`, `<iframe>`,
event handlers and DOM sinks and drops display markup; JS/TS strips comments (string-aware, so URLs
survive) and keeps declarations, control flow, and security lines (eval, fetch, innerHTML,
postMessage, addEventListener, process.env, ...). Files are prioritised by the ast map (LLM calls, prompts,
tools, agents) so the relevant ones are sent first, then chunked across a few calls. Try it:

```bash
python -m sentinel.reducer path/to/file.py focus     # reduced source; ratio printed to stderr
python -m sentinel.reducer path/to/template.html     # security-relevant HTML only
python -m sentinel.reducer path/to/app.js focus      # JS/TS: keeps sinks, fetch, handlers, env
```

Add a new file type by writing `sentinel/reducer/<type>_reducer.py` with `reduce(text, mode)` and
registering it in `REDUCERS`.

### Behavioral probing (issues static analysis can't see, e.g. LLM02)

Some risks only show in what the app SAYS - sensitive-info disclosure (LLM02), behavioral excessive
agency. `probe` runs behavioral probes through the harness and judges the reply with an LLM-judge.

```bash
SENTINEL_LLM=anthropic python -m sentinel.cli probe /path/to/app --target-llm anthropic
```

**For a web app, use the HTTP adapter - no `run_case.py` needed.** Start the app, then point
`probe --http` at its endpoint. Sentinel POSTs each probe and reads the reply:

```bash
# Start your app, then point probe at its chat endpoint:
SENTINEL_LLM=anthropic python -m sentinel.cli probe /path/to/app     --http http://localhost:8000/api/chat --target-llm anthropic
```

The response shape is configurable via a `sentinel.http.json` in the app's directory (and
`analyze` auto-detects one for you - see the self-configuring flow below). It looks like:

```json
{ "url": "http://localhost:8000/api/chat", "message_field": "message",
  "extra_body": {"history": []}, "reply_path": "response", "actions_path": "actions_executed" }
```

Set `reply_path` to wherever the reply lives in the response JSON (e.g. `message.content` or
`choices.0.message.content`). Then just `python -m sentinel.cli probe <dir> --target-llm anthropic`.
Without the judge LLM the probe never false-alarms (it reports "judge unavailable").

### Auto-probe loop (confirm the LLM-proposed weaknesses)

`analyze` with `SENTINEL_LLM=anthropic` proposes weaknesses (detector `llm`). `autoprobe` closes
the loop: for each, the LLM generates a concrete single-turn probe, runs it against the app, and an
LLM judge decides if the bad outcome occurred. Confirmed weaknesses become `status: confirmed` with
the transcript as evidence; the posture score then rates them `confirmed (dynamic probe)`.

```bash
SENTINEL_LLM=anthropic python -m sentinel.cli analyze /path/to/app          # proposes weaknesses
SENTINEL_LLM=anthropic python -m sentinel.cli autoprobe /path/to/app \
    --http http://localhost:8000/api/chat --target-llm anthropic            # confirms them
```

Needs a runnable app (`--http` for a web app, or the bundled run_case harness) and the judge LLM.
Results go to `runs/<app>/probe_results.json`; `findings.json` is updated in place. This is how an
LLM *proposal* becomes *evidence*, on any app - not just the bundled target.

**Zero-config auto-detect (the default).** During `analyze`, Sentinel statically reads the app's
README / Dockerfile / compose / source and any example request bodies (curl snippets, tests) to guess
the **port, chat endpoint, request fields, and reply path** - no LLM, no network - and writes
`runs/<app>/api_hints.json`. Then, if you run `autoprobe` with no `--http` and no `sentinel.http.json`,
it turns those hints into candidate configs, **verifies each against the running app**, and writes a
ready `sentinel.http.json` for the first that works. So for most apps you just start the app and run:

```bash
SENTINEL_LLM=anthropic python -m sentinel.cli analyze /path/to/app        # also writes api_hints.json
# start the app, then:
SENTINEL_LLM=anthropic python -m sentinel.cli autoprobe /path/to/app --safe --target-llm anthropic
```

Example request bodies are the most reliable source: a README line like
`curl ... -d '{"agent_id":"demo_agent","message":"hi","thread_id":null}'` gives real field names AND values,
so required fields like `agent_id` are filled in automatically. You only hand-write `sentinel.http.json`
when the app exposes no docs/example and an unusual request shape.

**Before any probe runs, `autoprobe` verifies the endpoint** (sends one benign message and checks a
usable reply comes back at `reply_path`). If the check fails it stops and prints what to fix, so you
never fire probes blindly at a wrong URL or path. The sample reply is printed on success - eyeball it
to confirm `reply_path` is right.

**Don't know the endpoint? Let it discover one.** `--discover <base-url>` probes a short list of
common chat paths (`/api/chat`, `/chat`, `/v1/chat/completions`, ...) and message/reply field names,
then writes a ready `sentinel.http.json` into the app's run dir:

```bash
SENTINEL_LLM=anthropic python -m sentinel.cli autoprobe /path/to/app \
    --discover http://localhost:8000 --target-llm anthropic
```

**`--safe` (dry-run) for live apps with real side effects.** Probing a write action (refunds, email,
file/DB writes) on a *live* backend can cause real damage. `--safe` skips every write-risky weakness
(all family-3 "action from model output" findings, plus any probe whose text mentions a write verb)
and runs only read-only probes (e.g. prompt-leak). Any probe that still triggers a real tool call is
flagged `[TOOLS EXECUTED: ...]` in its result so you see it immediately. Use `--safe` first on
anything connected to production:

```bash
SENTINEL_LLM=anthropic python -m sentinel.cli autoprobe /path/to/app \
    --discover http://localhost:8000 --safe --target-llm anthropic
```

Clone and scan a public repo the same way:

```bash
git clone https://github.com/<org>/<agent-repo> /tmp/target-app
python -m sentinel.cli analyze /tmp/target-app
python -m sentinel.cli report  /tmp/target-app
python -m sentinel.cli score   /tmp/target-app     # posture grade (no answer key needed)
```

Notes:
- `score` auto-adapts: with an `answer_key.yaml` it reports accuracy (recall/precision); without one
  (a real app) it reports a **security posture grade** - severity-weighted risk, per-weakness
  confidence, and scan coverage. It never claims accuracy it can't measure without ground truth.
- The Semgrep rules in `sentinel/checks/rules/core.yaml` are tuned for common Python LLM
  patterns (OpenAI/Anthropic SDKs, LangChain/LangGraph, f-string prompts, `send_/delete_` tools).
  Expect false positives/negatives on an unfamiliar codebase - read the findings, don't trust the count.

## 2. Fixing a new app - `remediate` (no wiring, no demo-specific code)

Fixes are **not** hardcoded per app. For any codebase, `remediate` reads your real findings, opens
the actual faulty source, and asks a model for a concrete fix anchored to each family's
model-independent control - validating every suggestion without touching your code:

```bash
SENTINEL_LLM=anthropic python -m sentinel.cli analyze   /path/to/app
SENTINEL_LLM=anthropic python -m sentinel.cli remediate /path/to/app
```

It writes `runs/<app>/remediation.md` (diagnosis, the suggested patch as a diff, rationale, and
verification steps) and `runs/<app>/suggested_fixes/<id>.patch` for you to review and `git apply`.

### Optional: dynamic red-team on a new app

Static analysis and remediation work on any app as-is. To also run the *offline* `attack`/`redteam`
harness against a new app (rather than probing it over HTTP with `autoprobe`), add an entry point
the harness can drive - a `run_case.py` that reads one JSON case from stdin and prints
`{reply, tool_log, outbox, tokens}` (see `targets/helpdeskbot/app/run_case.py`) - and app-specific
payloads in `sentinel/attacks/corpus.yaml`. For a running web app, prefer `autoprobe` instead (no
wiring needed).
