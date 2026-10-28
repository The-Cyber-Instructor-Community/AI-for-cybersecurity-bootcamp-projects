"""Reduce JavaScript / TypeScript source for LLM understanding.

JS has no stdlib AST, so this works on text: a small state machine strips comments (without being
fooled by // inside strings or URLs), then:
  * "minify"  - returns the comment-stripped, blank-line-free source (logic preserved).
  * "focus"   - keeps declarations / control structure AND security-relevant lines, dropping verbose
                inner expressions. If that leaves too little, it returns the full stripped source
                (so a file is never reduced to nothing).

Security-relevant JS: code execution and DOM-injection sinks, network calls, messaging, storage,
env/secrets, and anything that puts data into the page or runs it.
"""
from __future__ import annotations

import re

JS_SECURITY = re.compile(
    r"(eval\(|new\s+Function|Function\(|innerHTML|outerHTML|insertAdjacentHTML|document\.write"
    r"|dangerouslySetInnerHTML|srcdoc|javascript:|fetch\(|XMLHttpRequest|axios|\$\.(ajax|get|post)"
    r"|WebSocket|EventSource|importScripts|postMessage|onmessage|addEventListener|location\.|location\s*="
    r"|window\.open|document\.cookie|localStorage|sessionStorage|indexedDB|process\.env"
    r"|child_process|exec\(|spawn\(|require\(|import\(|crypto|token|secret|password|api[_]?key|credential"
    r"|setAttribute|href\s*=|src\s*=|registerRoute|serviceWorker|caches|skipWaiting)",
    re.I,
)
JS_STRUCT = re.compile(
    r"^\s*(import\b|export\b|const\b|let\b|var\b|function\b|class\b|async\b|return\b"
    r"|if\b|for\b|while\b|switch\b|case\b|try\b|catch\b|finally\b|\}|\)|\.then|\.catch|.*=>)",
)


def _strip_comments(src: str) -> str:
    out, i, n, state = [], 0, len(src), None   # state: None | ' | " | ` | // | /*
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state is None:
            if c == "/" and nxt == "/":
                state = "//"; i += 2; continue
            if c == "/" and nxt == "*":
                state = "/*"; i += 2; continue
            if c in "'\"`":
                state = c; out.append(c); i += 1; continue
            out.append(c); i += 1; continue
        if state in ("'", '"', "`"):
            out.append(c)
            if c == "\\":
                out.append(nxt); i += 2; continue
            if c == state:
                state = None
            i += 1; continue
        if state == "//":
            if c == "\n":
                state = None; out.append(c)
            i += 1; continue
        if state == "/*":
            if c == "*" and nxt == "/":
                state = None; i += 2; continue
            i += 1; continue
    return "".join(out)


def reduce(text: str, mode: str = "focus") -> str:
    lines = [ln.rstrip() for ln in _strip_comments(text).splitlines() if ln.strip()]
    if mode != "focus":
        return "\n".join(lines)
    kept = [ln for ln in lines if JS_SECURITY.search(ln) or JS_STRUCT.search(ln)]
    return "\n".join(kept if len(kept) >= 5 else lines)   # never reduce to almost nothing
