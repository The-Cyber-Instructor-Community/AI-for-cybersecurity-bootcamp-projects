"""
Shared foundation for the AI-SOC-Copilot agent pipeline.

Holds the CaseContext object passed through the pipeline, the Claude client +
tool-use loop, and the agentic-playbook loader/composer. Secrets come from the
environment (injected by `op run --env-file=.env -- ...`); nothing is read from
disk in plaintext.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
PLAYBOOK_DIR = PROJECT_ROOT / "playbooks"
CASES_DIR = PROJECT_ROOT / "cases"

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

# Model split (ARCHITECTURE.md): Sonnet for the reasoning-heavy triage, Haiku for
# the lighter response/notes formatting tasks. Override via env if needed.
TRIAGE_MODEL = os.environ.get("TRIAGE_MODEL", "claude-sonnet-5")
RESPONSE_MODEL = os.environ.get("RESPONSE_MODEL", "claude-haiku-4-5-20251001")
NOTES_MODEL = os.environ.get("NOTES_MODEL", "claude-haiku-4-5-20251001")

# Which of our Wazuh rule IDs map to which MITRE technique. We own the rules, so
# this mapping is authoritative and independent of Wazuh's mitre enrichment.
RULE_TECHNIQUE = {
    "100010": "T1547.011", "100011": "T1547.011",
    "100012": "T1547.011", "100013": "T1547.011",
    "100014": "T1546.004",             # shell config modification
    "100020": "T1059.002", "100021": "T1059.002",
    "100030": "T1547.011+T1546.004",   # correlation → compose both persistence playbooks
}

# Short, human-readable names for the MITRE techniques in scope (so IDs are legible
# in the UI and Slack without being verbose).
TECHNIQUE_NAMES = {
    "T1547.011": "LaunchAgent Persistence",
    "T1546.004": "Shell Config Modification",
    "T1059.002": "AppleScript Execution",
    "T1053.003": "Cron Persistence",
}


def technique_label(tid: str) -> str:
    name = TECHNIQUE_NAMES.get(tid)
    return f"{tid} — {name}" if name else tid


# --------------------------------------------------------------------------- #
# CaseContext — the single object threaded through the pipeline
# --------------------------------------------------------------------------- #

@dataclass
class CaseContext:
    alert: dict
    techniques: list[str] = field(default_factory=list)
    case_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    triage: dict | None = None       # {verdict, confidence, rationale, key_findings}
    enrichment: dict = field(default_factory=dict)  # raw tool outputs collected
    response: dict | None = None     # {proposed_actions, approval, executed, ...}
    note_path: str | None = None

    # --- convenience accessors over the raw Wazuh alert ---
    @property
    def rule_id(self) -> str:
        return str(self.alert.get("rule", {}).get("id", ""))

    @property
    def rule_description(self) -> str:
        return self.alert.get("rule", {}).get("description", "")

    @property
    def rule_level(self) -> int:
        return int(self.alert.get("rule", {}).get("level", 0))

    @property
    def agent_name(self) -> str:
        return self.alert.get("agent", {}).get("name", "unknown")

    @property
    def file_path(self) -> str | None:
        """The FIM path that triggered a persistence alert, if any."""
        return self.alert.get("syscheck", {}).get("path")

    @property
    def file_sha256(self) -> str | None:
        return self.alert.get("syscheck", {}).get("sha256_after")

    def to_dict(self) -> dict:
        return asdict(self)


def techniques_for_alert(alert: dict) -> list[str]:
    """Deterministically map an alert to MITRE technique(s) by our rule id.

    Falls back to the alert's own mitre.id enrichment if the rule isn't ours.
    """
    rid = str(alert.get("rule", {}).get("id", ""))
    mapped = RULE_TECHNIQUE.get(rid)
    if mapped:
        return mapped.split("+")
    return list(alert.get("rule", {}).get("mitre", {}).get("id", []))


# --------------------------------------------------------------------------- #
# Agentic playbook loader + composition
# --------------------------------------------------------------------------- #

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class Playbook:
    technique: str
    kind: str                # "triage" | "response"
    meta: dict               # parsed YAML frontmatter
    body: str                # the markdown instructions

    @property
    def confidence_threshold(self) -> int:
        return int(self.meta.get("confidence_threshold", 70))


def load_playbook(technique: str, kind: str) -> Playbook:
    """Load playbooks/<technique>/<kind>.md and split frontmatter from body."""
    path = PLAYBOOK_DIR / technique / f"{kind}.md"
    if not path.exists():
        raise FileNotFoundError(f"No {kind} playbook for {technique}: {path}")
    raw = path.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(raw)
    if not m:
        return Playbook(technique, kind, {}, raw)
    meta = yaml.safe_load(m.group(1)) or {}
    return Playbook(technique, kind, meta, m.group(2).strip())


def compose_playbooks(techniques: list[str], kind: str) -> list[Playbook]:
    """Load all playbooks matching the alert's technique(s).

    Deterministic selection (by technique); the agent synthesizes across the
    returned playbooks when there is more than one (multi-technique alerts).
    """
    out = []
    for t in techniques:
        try:
            out.append(load_playbook(t, kind))
        except FileNotFoundError:
            continue
    return out


# --------------------------------------------------------------------------- #
# Claude client + tool-use loop
# --------------------------------------------------------------------------- #

def _client():
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Run via: op run --env-file=.env -- python ...")
    return anthropic.Anthropic()


def claude_complete(*, model: str, system: str, prompt: str,
                    max_tokens: int = 1500, temperature: float | None = None) -> str:
    """Single-shot completion (no tools). Returns the text.

    temperature is omitted from the request unless explicitly set — the newest
    models (e.g. claude-sonnet-5) deprecate/reject the parameter.
    """
    kwargs = {"model": model, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": prompt}]}
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = _client().messages.create(**kwargs)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def claude_tool_loop(*, model: str, system: str, prompt: str, tools: list[dict],
                     dispatch, max_tokens: int = 2000, max_iters: int = 8) -> tuple[str, list[dict]]:
    """Run a tool-use loop until Claude stops requesting tools.

    tools    : Anthropic tool schemas.
    dispatch : callable(name, input_dict) -> result (json-serializable).
    Returns (final_text, tool_trace) where tool_trace records each call/result.
    """
    client = _client()
    messages = [{"role": "user", "content": prompt}]
    trace: list[dict] = []

    for _ in range(max_iters):
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            tools=tools, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return text, trace

        results = []
        for tu in tool_uses:
            try:
                out = dispatch(tu.name, tu.input)
            except Exception as exc:  # tool failures are data, not crashes
                out = {"error": str(exc)}
            trace.append({"tool": tu.name, "input": tu.input, "output": out})
            results.append({
                "type": "tool_result", "tool_use_id": tu.id,
                "content": json.dumps(out)[:6000],
            })
        messages.append({"role": "user", "content": results})

    return "(max tool iterations reached)", trace


def extract_json(text: str) -> dict:
    """Best-effort: pull the first JSON object out of an LLM reply."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


# --------------------------------------------------------------------------- #
# Live UI reporting — the pipeline POSTs stage events to the (optional) UI
# service over HTTP. Fully decoupled: no-op if the UI isn't running, and the
# UI can run anywhere (localhost now, next to Wazuh later) via UI_URL.
# --------------------------------------------------------------------------- #

def ui_report(stage: str, payload: dict) -> None:
    url = os.environ.get("UI_URL", "http://localhost:5001")
    try:
        import requests
        requests.post(f"{url}/event", json={"stage": stage, **payload}, timeout=1.5)
    except Exception:
        pass  # UI optional — never break the pipeline on a reporting failure
