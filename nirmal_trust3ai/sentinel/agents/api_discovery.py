"""Static (zero-token) discovery of a web app's chat API shape, for auto-probing.

Runs during `analyze`. Reads README / Dockerfile / compose / source and any example request
bodies (curl snippets, test fixtures) to work out, WITHOUT calling an LLM or the running app:

  - which PORT the backend listens on,
  - the chat ENDPOINT path,
  - the request shape (which field carries the user message, plus any other required fields),
  - where the REPLY and any tool-call list live in the response JSON.

The result is saved as `api_hints.json`. `autoprobe` turns these hints into candidate
HttpConfigs, verifies each against the live app, and writes a ready `sentinel.http.json` -
so the user rarely has to configure anything by hand.

Everything here is best-effort pattern matching. It never has to be perfect: the live
verify step in autoprobe is the final judge of which candidate actually works.
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

# Field-name vocabularies (ordered by preference).
MESSAGE_FIELDS = ["message", "query", "prompt", "input", "text", "question", "content", "msg"]
REPLY_FIELDS = ["reply", "response", "answer", "output", "content", "message", "text", "result"]
ACTION_FIELDS = ["tools_called", "actions_executed", "actions", "tools", "tool_calls", "function_calls"]
CHAT_HINT = ("chat", "message", "ask", "query", "complet", "agent", "conversation", "prompt", "generate")

# Where to look, and what to skip.
TEXT_GLOBS = ["*.py", "*.js", "*.ts", "*.md", "*.txt", "*.sh", "*.http", "*.yaml", "*.yml",
              "*.toml", "*.env", "*.cfg", "*.ini", "Dockerfile", "Makefile", "*.json"]
SKIP = {"node_modules", ".git", ".venv", "venv", "dist", "build", "__pycache__", "site-packages",
        ".claude", "worktrees", ".next", ".turbo", "coverage", "__snapshots__", "migrations"}
# Design docs carry illustrative JSON (log schemas, event payloads) that must NOT be read as a chat
# request body. We still read README/usage/client/test files for real request examples.
LOOSE_BODY_OK = re.compile(r"(readme|usage|quickstart|getting[-_]?started|example|client|curl|test|\.http)",
                           re.IGNORECASE)
# A JSON object that is really a log/event record, not a chat request.
LOG_RECORD_FIELDS = {"level", "logger", "ts", "timestamp", "request_id", "thread", "lineno",
                     "severity", "levelname", "asctime", "pathname", "funcname", "trace_id", "span_id"}
MAX_FILES = 900
MAX_BYTES = 200_000     # per file; docs/source rarely need more

# Framework -> conventional default port, used only when nothing explicit is found.
FRAMEWORK_DEFAULT_PORT = {"fastapi": 8000, "uvicorn": 8000, "flask": 5000, "express": 3000,
                          "next": 3000, "django": 8000, "starlette": 8000}


class ApiHints(BaseModel):
    """Best-guess chat API shape, with human-readable evidence for every guess."""
    base_url: str | None = None
    candidate_ports: list[int] = Field(default_factory=list)
    endpoints: list[str] = Field(default_factory=list)
    message_field: str | None = None
    extra_fields: dict = Field(default_factory=dict)      # non-message body fields, with example/default values
    reply_path: str | None = None
    actions_path: str | None = None
    frameworks: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


API_NAME_HINT = ("api", "server", "main", "app", "route", "router", "chat", "endpoint",
                 "backend", "handler", "view", "controller", "readme", "docker", "compose")


def _file_rank(rel: str) -> tuple:
    low = rel.lower()
    name_hit = any(k in low for k in API_NAME_HINT)
    is_src = low.endswith((".py", ".js", ".ts", ".md", "dockerfile", ".yml", ".yaml"))
    return (not name_hit, not is_src, rel.count("/"), len(rel))   # likely API files first


def _iter_files(root: Path):
    cands = [p for p in root.rglob("*")
             if p.is_file() and not (SKIP & set(p.relative_to(root).parts))
             and (p.name in ("Dockerfile", "Makefile") or any(p.match(g) for g in TEXT_GLOBS))]
    cands.sort(key=lambda p: _file_rank(str(p.relative_to(root))))
    for p in cands[:MAX_FILES]:
        yield p


def _read(p: Path) -> str:
    try:
        return p.read_text(errors="ignore")[:MAX_BYTES]
    except Exception:
        return ""


# --- ports -----------------------------------------------------------------
PORT_PATTERNS = [
    (re.compile(r"EXPOSE\s+(\d{2,5})"), "Dockerfile EXPOSE"),
    (re.compile(r"--port[=\s]+(\d{2,5})"), "--port flag"),
    (re.compile(r"\.run\([^)]*port\s*=\s*(\d{2,5})"), "run(port=)"),
    (re.compile(r"\bport\s*[:=]\s*(\d{2,5})"), "port= / port:"),
    (re.compile(r"\.listen\(\s*(\d{2,5})"), ".listen(port)"),
    (re.compile(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d{2,5})"), "localhost:PORT"),
    (re.compile(r"\bPORT\s*=\s*(\d{2,5})"), "PORT env"),
    (re.compile(r"-p\s+(\d{2,5}):\d{2,5}"), "compose ports"),
]


def _find_ports(texts: list[tuple[str, str]], frameworks: set[str], ev: list[str]) -> list[int]:
    weight: Counter[int] = Counter()
    for name, text in texts:
        for rx, label in PORT_PATTERNS:
            for m in rx.finditer(text):
                port = int(m.group(1))
                if 1024 <= port <= 65535 and port not in (11434,):   # skip Ollama's own port
                    # explicit run/expose/compose configs are stronger signals than a stray localhost
                    strong = label in ("Dockerfile EXPOSE", "--port flag", "run(port=)", "compose ports", "PORT env")
                    weight[port] += 3 if strong else 1
    ports = [p for p, _ in weight.most_common(5)]
    for fw in frameworks:                                   # conventional fallback
        d = FRAMEWORK_DEFAULT_PORT.get(fw)
        if d and d not in ports:
            ports.append(d)
    if ports:
        ev.append(f"ports: {ports} (from EXPOSE/--port/localhost refs and framework defaults)")
    return ports


# --- endpoints -------------------------------------------------------------
ROUTE_PATTERNS = [
    re.compile(r"@\w+\.(?:post|api_route|route)\(\s*[\"']([^\"']+)[\"']"),   # FastAPI/Flask decorators
    re.compile(r"\.(?:post|all)\(\s*[\"']([^\"']+)[\"']"),                    # express .post('/path'
    re.compile(r"[\"'](/[A-Za-z0-9_\-/]*(?:chat|message|ask|query|complet|agent|generate)[A-Za-z0-9_\-/]*)[\"']"),
]


def _find_endpoints(texts: list[tuple[str, str]], ev: list[str]) -> list[str]:
    paths: list[str] = []
    for _, text in texts:
        for rx in ROUTE_PATTERNS:
            for m in rx.finditer(text):
                path = m.group(1)
                if path.startswith("/") and path not in paths and len(path) < 60:
                    paths.append(path)

    def rank(path: str):
        low = path.lower()
        hit = next((i for i, k in enumerate(CHAT_HINT) if k in low), len(CHAT_HINT))
        return (any(sp in low for sp in STREAMY), hit, path.count("/"), len(path))  # plain+shallow first

    chatty = [p for p in paths if any(k in p.lower() for k in CHAT_HINT)
              and not any(seg in NEGATIVE_SEG for seg in p.strip("/").split("/"))]  # drop /chat/evil, /chat/x
    chatty = sorted(chatty, key=rank)
    if chatty:
        ev.append(f"endpoints: {chatty[:5]} (chat-like routes found in source)")
    return chatty[:6]


# --- request shape ---------------------------------------------------------
# raw dict access: body.get("x"[, default]) / request.json["x"] / data["x"] / payload.get("x")
GET_RX = re.compile(r"(?:\breq\.body|\brequest\.json|\b(?:body|data|payload|json))"
                    r"(?:\.get\(\s*[\"'](\w+)[\"']\s*(?:,\s*([^)]+))?\)|\[\s*[\"'](\w+)[\"']\s*\])")


def _parse_literal(raw: str | None):
    if raw is None:
        return None
    try:
        return ast.literal_eval(raw.strip())
    except Exception:
        return None


def _pydantic_models(py_text: str) -> list[tuple[str, dict]]:
    """Return (class_name, {field: (has_default, default_value)}) for BaseModel subclasses."""
    out = []
    try:
        tree = ast.parse(py_text)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
                (isinstance(b, ast.Name) and b.id.endswith("Model")) or
                (isinstance(b, ast.Name) and b.id == "BaseModel") or
                (isinstance(b, ast.Attribute) and b.attr == "BaseModel") for b in node.bases):
            fields = {}
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    has_def = stmt.value is not None
                    val = None
                    if has_def:
                        try:
                            val = ast.literal_eval(stmt.value)
                        except Exception:
                            val = None
                    fields[stmt.target.id] = (has_def, val)
            if fields:
                out.append((node.name, fields))
    return out


# Values that mark a negative / placeholder example (error-path tests, templates) - never real config.
NEGATIVE_VALUE = re.compile(
    r"(no[_-]?such|non[_-]?exist|does[_-]?not|invalid|unknown|missing|fake|dummy|"
    r"placeholder|changeme|your[_-]|\bfoo\b|\bbar\b|\bbaz\b|\bevil\b|\btodo\b|xxx)", re.IGNORECASE)
NEGATIVE_SEG = {"evil", "x", "foo", "bar", "baz", "test", "demo", "example", "dummy", "bad"}
STREAMY = ("stream", "sse", "cancel", "ws", "websocket", "subscribe")


def _is_id_like(key: str) -> bool:
    k = key.lower()
    return k.endswith("_id") or k in ("agent", "agent_id", "assistant", "model", "bot", "persona")


def _is_negative_body(obj: dict) -> bool:
    """True if an id-like field holds a negative/placeholder value (an error-path or template example)."""
    for k, v in obj.items():
        if _is_id_like(k) and isinstance(v, str) and NEGATIVE_VALUE.search(v):
            return True
    return False


def _sanitize_body(obj: dict) -> dict:
    """Blank out id-like fields with negative/placeholder values so autoprobe discovers the real one."""
    return {k: (None if (_is_id_like(k) and isinstance(v, str) and NEGATIVE_VALUE.search(v)) else v)
            for k, v in obj.items()}


def _is_log_record(obj: dict) -> bool:
    """True if a JSON object looks like a log/telemetry record rather than a chat request."""
    return len(LOG_RECORD_FIELDS & {k.lower() for k in obj}) >= 2


def _looks_like_chat_body(obj: dict) -> bool:
    """A plausible chat request: has a message-ish field with a string value, and isn't a log record."""
    if not isinstance(obj, dict) or _is_log_record(obj):
        return False
    msg = next((k for k in MESSAGE_FIELDS if k in obj), None)
    return bool(msg) and isinstance(obj.get(msg), str)


# A URL (optional host+port) with a chat-like path, as it appears in curl/fetch/requests examples.
CHAT_URL_RX = re.compile(
    r"""["'`]?(?:(https?://)(?P<host>[A-Za-z0-9_.\-]+)(?::(?P<port>\d{2,5}))?)?"""
    r"""(?P<path>/[A-Za-z0-9_./\-]*(?:chat|message|ask|query|complet|agent|generate|conversation)[A-Za-z0-9_./\-]*)""",
    re.IGNORECASE)


def _coupled_examples(texts):
    """Find (path, port, body) triples where a chat URL and a request body appear together.

    This ties endpoint + port + request shape to ONE real example (a curl, fetch, or .post call),
    which is far more reliable on a big repo than scanning each field independently.
    """
    out = []
    for name, text in texts:
        for um in CHAT_URL_RX.finditer(text):
            path = um.group("path")
            if len(path) > 60 or path.endswith((".md", ".py", ".js", ".ts", ".html")):
                continue
            port = int(um.group("port")) if um.group("port") else None
            window = text[um.start(): um.end() + 600]        # body usually follows the URL
            for obj in _json_objects_with_message(window):
                if _looks_like_chat_body(obj):
                    out.append((name, path, port, obj))
                    break

    def rank(item):
        name, path, port, obj = item
        low = path.lower()
        chatness = next((i for i, k in enumerate(CHAT_HINT) if k in low), len(CHAT_HINT))
        return (
            _is_negative_body(obj),                          # positive examples first
            any(seg in NEGATIVE_SEG for seg in path.strip("/").split("/")),  # not a test route
            any(sp in low for sp in STREAMY),                # plain before streaming/cancel
            "test" in name.lower(),                          # docs/client before test files
            chatness, len(obj), 0 if port else 1,
        )

    return sorted(out, key=rank)


def _find_request_shape(texts, ev):
    """Return (message_field, extra_fields). Example bodies > pydantic models > raw .get() calls."""
    # 1) Loose example bodies, but ONLY in usage/test/client files and never a log-record shape.
    for name, text in texts:
        if not LOOSE_BODY_OK.search(name):
            continue
        for obj in _json_objects_with_message(text):
            if not _looks_like_chat_body(obj):
                continue
            msg = next((k for k in MESSAGE_FIELDS if k in obj), None)
            extra = {k: v for k, v in obj.items() if k != msg and k not in REPLY_FIELDS}
            ev.append(f"request shape from example body in {name}: message_field={msg}, extra={extra}")
            return msg, extra

    # 2) Pydantic request model whose fields include a message synonym.
    for name, text in texts:
        if not name.endswith(".py"):
            continue
        for cls, fields in _pydantic_models(text):
            msg = next((k for k in MESSAGE_FIELDS if k in fields), None)
            if msg:
                extra = {k: (v if has else None) for k, (has, v) in fields.items()
                         if k != msg and k not in REPLY_FIELDS}
                ev.append(f"request shape from pydantic {cls} in {name}: message_field={msg}, extra={extra}")
                return msg, extra

    # 3) Raw dict access on the request body.
    keys: dict[str, object] = {}
    for _, text in texts:
        for m in GET_RX.finditer(text):
            key = m.group(1) or m.group(3)
            if key:
                keys.setdefault(key, _parse_literal(m.group(2)))
    msg = next((k for k in MESSAGE_FIELDS if k in keys), None)
    if msg:
        extra = {k: v for k, v in keys.items() if k != msg and k not in REPLY_FIELDS}
        ev.append(f"request shape from body.get() calls: message_field={msg}, extra={extra}")
        return msg, extra
    return None, {}


def _json_objects_with_message(text: str) -> list[dict]:
    """Find brace-balanced JSON objects that mention a message field, and parse the parseable ones."""
    out = []
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        depth, j = 0, i
        while j < len(text) and j < i + 2000:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blob = text[i:j + 1]
        if not any(f'"{k}"' in blob or f"'{k}'" in blob for k in MESSAGE_FIELDS):
            continue
        try:
            obj = json.loads(blob)
        except Exception:
            try:
                obj = ast.literal_eval(blob)                # tolerate single quotes / python-ish
            except Exception:
                continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


# --- reply shape -----------------------------------------------------------
# Inline response dicts: return {...} / JSONResponse({...}) / res.json({...}).
RETURN_DICT_RX = re.compile(r"(?:JSONResponse\(\s*(?:content\s*=\s*)?|return\s+|res\.json\(\s*)\{([^{}]*)\}")
# Dict assigned to a response-like variable: response_data = {...}.
ASSIGN_DICT_RX = re.compile(r"\b(\w*(?:resp|reply|result|answer|output|payload|data|content)\w*)\s*=\s*\{([^{}]*)\}",
                            re.IGNORECASE)
# Key added to a response-like variable: response_data["actions_executed"] = ...
SUBSCRIPT_RX = re.compile(r"\b\w*(?:resp|reply|result|answer|output|payload|data|content)\w*"
                          r"\[\s*[\"'](\w+)[\"']\s*\]\s*=", re.IGNORECASE)
KEY_RX = re.compile(r"[\"'](\w+)[\"']\s*:")


def _find_reply_shape(texts, message_field, ev):
    returned_keys: list[str] = []

    def add(k):
        if k and k not in returned_keys:
            returned_keys.append(k)

    for _, text in texts:
        for m in RETURN_DICT_RX.finditer(text):
            for k in KEY_RX.findall(m.group(1)):
                add(k)
        for m in ASSIGN_DICT_RX.finditer(text):
            for k in KEY_RX.findall(m.group(2)):
                add(k)
        for m in SUBSCRIPT_RX.finditer(text):
            add(m.group(1))
    reply = next((k for k in REPLY_FIELDS if k in returned_keys and k != message_field), None)
    actions = next((k for k in ACTION_FIELDS if k in returned_keys), None)
    if reply:
        ev.append(f"reply_path={reply}"
                  + (f", actions_path={actions}" if actions else "")
                  + f" (from response JSON keys {returned_keys[:8]})")
    return reply, actions


# --- frameworks ------------------------------------------------------------
def _find_frameworks(texts) -> set[str]:
    fw = set()
    joined = "\n".join(t for _, t in texts).lower()
    for name in ("fastapi", "uvicorn", "flask", "express", "starlette", "django", "next"):
        if name in joined:
            fw.add(name)
    return fw


def discover_api_static(root: str | Path) -> ApiHints:
    """Scan a repo and return best-guess chat API hints (no LLM, no network)."""
    root = Path(root)
    texts = [(str(p.relative_to(root)), _read(p)) for p in _iter_files(root)]
    ev: list[str] = []
    frameworks = _find_frameworks(texts)
    ports = _find_ports(texts, frameworks, ev)
    endpoints = _find_endpoints(texts, ev)

    # Best signal first: a real example that couples URL + port + body (curl/fetch/.post).
    message_field = extra = None
    coupled = _coupled_examples(texts)
    if coupled:
        name, path, port, obj = coupled[0]
        if _is_negative_body(obj):                                      # only a negative example was found
            obj = _sanitize_body(obj)
            ev.append("note: example's agent/id value looked like a negative-test placeholder -> "
                      "blanked for live auto-discovery")
        message_field = next((k for k in MESSAGE_FIELDS if k in obj), None)
        extra = {k: v for k, v in obj.items() if k != message_field and k not in REPLY_FIELDS}
        # Pin the example's endpoint first only if it's a clean, non-streaming route; otherwise just
        # include it and let plain routes rank ahead (autoprobe can't read an SSE stream as JSON).
        low = path.lower()
        clean = not any(sp in low for sp in STREAMY) and not any(
            seg in NEGATIVE_SEG for seg in path.strip("/").split("/"))
        if clean:
            endpoints = [path] + [e for e in endpoints if e != path]
        elif path not in endpoints:
            endpoints = endpoints + [path]
        if port:
            ports = [port] + [p for p in ports if p != port]            # and its port
        ev.append(f"coupled example in {name}: {path}"
                  + (f" :{port}" if port else "") + f", message_field={message_field}, extra={extra}")

    if message_field is None:                                           # fall back to independent extraction
        message_field, extra = _find_request_shape(texts, ev)
    extra = extra or {}
    reply_path, actions_path = _find_reply_shape(texts, message_field, ev)
    base_url = f"http://localhost:{ports[0]}" if ports else None
    return ApiHints(base_url=base_url, candidate_ports=ports, endpoints=endpoints,
                    message_field=message_field, extra_fields=extra, reply_path=reply_path,
                    actions_path=actions_path, frameworks=sorted(frameworks), evidence=ev)


def to_http_configs(hints: ApiHints, max_candidates: int = 28):
    """Turn hints into ranked candidate HttpConfigs to verify against the live app.

    Endpoint-MAJOR order: the top endpoint is tried on EVERY candidate port before the second
    endpoint on any port. This guarantees the real port is reached even when it ranks low and the
    candidate list is capped (e.g. the live port sitting 3rd behind two framework defaults).
    """
    from sentinel.harness.http_adapter import HttpConfig
    ports = hints.candidate_ports or [8000, 5000, 3000]
    endpoints = (hints.endpoints or ["/api/chat", "/chat"])[:4]
    msg = hints.message_field or "message"
    reply = hints.reply_path or "reply"
    configs = []
    for ep in endpoints:
        for port in ports:
            configs.append(HttpConfig(
                url=f"http://localhost:{port}{ep}", message_field=msg,
                extra_body=dict(hints.extra_fields), reply_path=reply,
                actions_path=hints.actions_path))
            if len(configs) >= max_candidates:
                return configs
    return configs
