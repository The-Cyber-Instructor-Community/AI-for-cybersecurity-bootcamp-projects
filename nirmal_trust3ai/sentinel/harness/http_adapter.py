"""HTTP harness adapter - probe a RUNNING web app over HTTP, with no per-app run_case.py.

Many AI apps are web services (FastAPI/Flask + a chat endpoint). This adapter POSTs one message
to the app's endpoint and returns the same {reply, tool_log, outbox, tokens} shape the oracles
expect, so behavioral probing and the LLM-judge work unchanged.

It is configurable because apps differ in request/response shape. Config (JSON, per target):

    {
      "url": "http://localhost:8000/api/chat",
      "message_field": "message",          # where the probe text goes in the request body
      "extra_body": {"history": []},       # static fields the endpoint requires
      "reply_path": "response",            # dotted path to the reply text in the JSON response
      "actions_path": "actions_executed"   # optional: dotted path to a list of actions taken
    }

Uses only the standard library (urllib), so it adds no dependency. Runs wherever it can reach
the app (e.g. on the user's machine for a localhost server).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

# Reply keys tried when reply_path is absent or does not resolve.
REPLY_FALLBACKS = ["response", "reply", "message.content", "content", "text",
                   "choices.0.message.content", "output", "answer"]


class HttpConfig(BaseModel):
    url: str
    method: str = "POST"
    message_field: str = "message"
    extra_body: dict = Field(default_factory=dict)
    headers: dict = Field(default_factory=dict)
    reply_path: str = "response"
    actions_path: str | None = None
    timeout: float = 90.0

    @classmethod
    def load(cls, source: str | Path | dict) -> "HttpConfig":
        if isinstance(source, dict):
            return cls(**source)
        return cls(**json.loads(Path(source).read_text()))


def _dig(data, path: str):
    """Follow a dotted path through dicts/lists: 'message.content', 'choices.0.message.content'."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _extract_reply(data, reply_path: str) -> str:
    for path in [reply_path, *REPLY_FALLBACKS]:
        value = _dig(data, path)
        if isinstance(value, str) and value:
            return value
    return json.dumps(data)                         # last resort: the whole body as text


# For auto-discovery: ordered candidates tried against a base URL.
DISCOVER_ENDPOINTS = ["/api/chat", "/chat", "/api/chat/completions", "/v1/chat/completions",
                      "/api/message", "/api/ask", "/api/query", "/message", "/ask", "/api/agent/chat"]
DISCOVER_MESSAGE_FIELDS = ["message", "query", "prompt", "input", "text", "question"]
DISCOVER_REPLY_PATHS = ["reply", "response", "message", "content", "answer", "text",
                        "choices.0.message.content", "message.content", "output", "data.reply"]


def _looks_like_reply(data, reply_path: str) -> str | None:
    """Return a clean reply if reply_path (or a fallback) resolves to real text, else None."""
    for path in [reply_path, *DISCOVER_REPLY_PATHS]:
        v = _dig(data, path)
        if isinstance(v, str) and v.strip() and not v.lstrip().startswith("<"):
            return v
    return None


def probe_endpoint(config: HttpConfig, message: str) -> dict:
    """Send one message and CLASSIFY the outcome, so auto-config can tell a correct endpoint that
    merely errored (e.g. the app's own LLM is down) from a wrong URL. Returns:
      {kind, status, detail, reply}  where kind is one of
      ok | reachable_no_reply | auth | not_found | bad_shape | app_error | unreachable.
    """
    body = {**config.extra_body, config.message_field: message}
    req = urllib.request.Request(config.url, data=json.dumps(body).encode(), method=config.method,
                                 headers={"Content-Type": "application/json", **config.headers})
    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            raw = resp.read().decode(errors="ignore")
            status = resp.status
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode(errors="ignore")[:300]
        except Exception:
            text = ""
        if e.code in (401, 403):
            return {"kind": "auth", "status": e.code, "detail": f"auth required ({e.code}): {text}", "reply": ""}
        if e.code == 404:
            return {"kind": "not_found", "status": 404, "detail": "no such endpoint (404)", "reply": ""}
        if e.code == 422:
            missing = _missing_fields_from_422(text)
            return {"kind": "bad_shape", "status": 422,
                    "detail": f"request shape rejected (422){'; missing ' + str(missing) if missing else ''}", "reply": ""}
        # Any other 4xx/5xx: the endpoint EXISTS and parsed our request, but the app errored.
        return {"kind": "app_error", "status": e.code,
                "detail": f"endpoint reached but the app returned HTTP {e.code}: {text}", "reply": ""}
    except urllib.error.URLError as e:
        return {"kind": "unreachable", "status": None, "detail": f"could not reach {config.url}: {e}", "reply": ""}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        if raw.strip() and not raw.lstrip().startswith("<"):
            return {"kind": "ok", "status": status, "detail": "ok (non-JSON reply)", "reply": raw[:200]}
        return {"kind": "reachable_no_reply", "status": status, "detail": "reached but reply was HTML/empty", "reply": ""}
    reply = _extract_reply(data, config.reply_path)
    if reply and not str(reply).lstrip().startswith("<"):
        return {"kind": "ok", "status": status, "detail": "ok", "reply": str(reply)[:200]}
    return {"kind": "reachable_no_reply", "status": status,
            "detail": f"reached (HTTP {status}) but no reply at '{config.reply_path}' (keys: "
                      f"{list(data)[:6] if isinstance(data, dict) else type(data).__name__})", "reply": ""}


def verify(config: HttpConfig, message: str = "Connectivity check: please reply with the word OK.") -> tuple[bool, str, str]:
    """Send one benign message and confirm a usable reply comes back. (ok, detail, sample_reply)."""
    r = probe_endpoint(config, message)
    return (r["kind"] == "ok"), r["detail"], r["reply"]


def _discover_agent(base: str) -> str | None:
    """Some apps need an agent_id. Try to read a default agent from a few list endpoints."""
    for path in ("/api/chat/agents", "/api/agents", "/agents"):
        try:
            with urllib.request.urlopen(urllib.request.Request(base + path), timeout=10) as r:
                data = json.loads(r.read().decode(errors="ignore"))
        except Exception:
            continue
        agents = data.get("agents") if isinstance(data, dict) else data
        if isinstance(agents, list) and agents:
            default = next((a for a in agents if isinstance(a, dict) and a.get("default")), agents[0])
            if isinstance(default, dict):
                return default.get("id") or default.get("agent_id")
    return None


def _missing_fields_from_422(err_body: str) -> list[str]:
    """Parse a FastAPI 422 body for the names of required body fields it is missing."""
    try:
        detail = json.loads(err_body).get("detail", [])
    except Exception:
        return []
    out = []
    for d in detail if isinstance(detail, list) else []:
        loc = d.get("loc") if isinstance(d, dict) else None
        if isinstance(loc, list) and loc and loc[0] == "body" and len(loc) > 1:
            if "required" in str(d.get("msg", "")).lower() or d.get("type", "").endswith("missing"):
                out.append(str(loc[1]))
    return out


# Candidate values to try for a required id-like field we can't know in advance.
_ID_GUESSES = ["default", "assistant", "agent"]


def _post_json(url: str, body: dict, timeout: float):
    """POST json; return (data, None) on 2xx json, or (None, (status, body_text))."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode(errors="ignore")), None
    except urllib.error.HTTPError as e:
        try:
            return None, (e.code, e.read().decode(errors="ignore"))
        except Exception:
            return None, (e.code, "")
    except Exception as e:
        return None, (None, str(e))


def discover(base_url: str, message: str = "Connectivity check: please reply with the word OK.",
             report: list | None = None) -> HttpConfig | None:
    """Probe a base URL for a working chat endpoint + request/response shape. Best-effort, bounded.

    When nothing fully works, `report` (if given) is filled with one human-readable line per endpoint
    that exists but needs more (e.g. a required body field), so the caller can tell the user what to add.
    """
    base = base_url.rstrip("/")
    agent_id = _discover_agent(base)
    base_extra = {"thread_id": None}
    if agent_id:
        base_extra = {"agent_id": agent_id, "thread_id": None}
    extra_bodies = [base_extra, {}]
    seen: dict[str, str] = {}

    def _try(url, field, extra):
        data, err = _post_json(url, {**extra, field: message}, 90.0)
        if data is not None:
            reply = _looks_like_reply(data, "reply")
            if reply is not None:
                good_path = next((pp for pp in DISCOVER_REPLY_PATHS if _dig(data, pp) == reply), "reply")
                return HttpConfig(url=url, message_field=field, extra_body=extra, reply_path=good_path,
                                  actions_path="tools_called" if _dig(data, "tools_called") is not None else None)
            seen[url] = f"{url} -> 200 but no reply field matched (keys: {list(data)[:6] if isinstance(data, dict) else type(data).__name__})"
            return None
        status, text = err
        if status == 404 or status is None:
            return None
        # Endpoint exists (4xx/5xx). If it's a 422 telling us which fields are missing, retry with them.
        missing = _missing_fields_from_422(text) if status == 422 else []
        extra_missing = [m for m in missing if m not in {field, *extra}]
        if extra_missing:
            # Fill id-like fields with guesses; others with a harmless placeholder.
            for guess in _ID_GUESSES:
                filled = dict(extra)
                for m in extra_missing:
                    filled[m] = guess if ("id" in m.lower() or "agent" in m.lower()) else "test"
                data2, err2 = _post_json(url, {**filled, field: message}, 90.0)
                if data2 is not None and _looks_like_reply(data2, "reply") is not None:
                    reply = _looks_like_reply(data2, "reply")
                    good_path = next((pp for pp in DISCOVER_REPLY_PATHS if _dig(data2, pp) == reply), "reply")
                    return HttpConfig(url=url, message_field=field, extra_body=filled, reply_path=good_path,
                                      actions_path="tools_called" if _dig(data2, "tools_called") is not None else None)
            seen[url] = (f"{url} -> 422, needs body field(s) {extra_missing} we can't guess. "
                         f"Add them to extra_body in sentinel.http.json.")
        else:
            seen.setdefault(url, f"{url} -> HTTP {status} (exists but the request shape is wrong)")
        return None

    for endpoint in DISCOVER_ENDPOINTS:
        for field in DISCOVER_MESSAGE_FIELDS[:3]:          # message/query/prompt cover most apps
            for extra in extra_bodies:
                cfg = _try(base + endpoint, field, extra)
                if cfg is not None:
                    return cfg
    if report is not None:
        report.extend(sorted(set(seen.values())))
    return None


def run_case_http(message: str, config: HttpConfig) -> dict:
    """Send one probe message to the running app and normalise its response for the oracles."""
    body = {**config.extra_body, config.message_field: message}
    req = urllib.request.Request(
        config.url, data=json.dumps(body).encode(), method=config.method,
        headers={"Content-Type": "application/json", **config.headers})
    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            raw = resp.read().decode(errors="ignore")
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach {config.url}: {e}. Is the app running?") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"reply": raw, "tool_log": [], "outbox": [], "tokens": 0}   # non-JSON reply
    reply = _extract_reply(data, config.reply_path)
    actions = _dig(data, config.actions_path) if config.actions_path else None
    tool_log = [{"tool": "action", "args": a} for a in actions] if isinstance(actions, list) else []
    return {"reply": reply, "tool_log": tool_log, "outbox": [], "tokens": 0}
