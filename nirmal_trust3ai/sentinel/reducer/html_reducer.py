"""Reduce HTML/template source to its SECURITY-relevant parts for LLM understanding.

Display markup (layout, text, styling) is dropped. We keep the parts that can execute code or
inject untrusted/LLM data into the page:
  * <script> and <iframe>/<object>/<embed> blocks (code execution / embedding)
  * event-handler attributes (onclick, onload, onerror, ...)
  * DOM-injection sinks in inline JS: innerHTML, outerHTML, insertAdjacentHTML, document.write,
    dangerouslySetInnerHTML, eval(, javascript: URLs
  * template interpolation where server/LLM data lands in the page: {{ }}, ${ }, <%= %>, {% %}
  * <form>/<input> (where user input enters) and src/href that are javascript: URLs
"""
from __future__ import annotations

import re

OPEN_BLOCK = re.compile(r"<\s*(script|iframe|object|embed)\b", re.I)
CLOSE_BLOCK = re.compile(r"<\s*/\s*(script|iframe|object|embed)\s*>", re.I)
INTEREST = re.compile(
    r"(\son\w+\s*=|<\s*(script|iframe|object|embed|form|input|textarea)\b"
    r"|innerHTML|outerHTML|insertAdjacentHTML|document\.write|dangerouslySetInnerHTML"
    r"|eval\(|javascript:|srcdoc\s*=|\{\{.*?\}\}|\$\{.*?\}|<%=?.*?%>|\{%.*?%\})",
    re.I | re.S,
)


def reduce(text: str, mode: str = "focus") -> str:
    kept, in_block = [], False
    for n, line in enumerate(text.splitlines(), 1):
        hit = in_block or bool(INTEREST.search(line))
        if OPEN_BLOCK.search(line):
            in_block = True
            hit = True
        if hit:
            kept.append(f"{n:5} {line.strip()}")
        if in_block and CLOSE_BLOCK.search(line):
            in_block = False
    return "\n".join(kept) if kept else "# (no security-relevant HTML found)"
