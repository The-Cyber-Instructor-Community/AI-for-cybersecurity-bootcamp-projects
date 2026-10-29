"""Reduce Python source for LLM understanding.

Two modes:
  * "minify"  - LOGIC-PRESERVING: drop comments, docstrings, blank lines; normalise whitespace
                (via ast.unparse). The program behaves identically; it is just smaller.
  * "focus"   - STRUCTURE for understanding: keep imports, decorators, class/function signatures
                and module constants in full, but ELIDE the bodies of functions that contain no
                security-relevant code (replaced with `...`). Security-relevant functions keep
                their body. This is not runnable - it is a security-focused skeleton that lets the
                LLM grasp a large app's shape in a fraction of the tokens.

Falls back to a line-based strip if the file does not parse.
"""
from __future__ import annotations

import ast
import re

# A function/method is kept in full when its code touches any of these.
SECURITY = re.compile(
    r"(messages\.create|chat\.completions|\.complete\(|\.invoke\(|generate_content"
    r"|\.post\(|\.stream\(|httpx|requests\.|aiohttp|urllib|openai|anthropic|ollama"
    r"|exec\(|eval\(|subprocess|os\.system|popen|compile\("
    r"|\.search\(|\.finditer\(|\.findall\(|\.match\("
    r"|\bsend_|\bdelete_|\bpost_|\bpublish_|\btransfer_|render|HTMLResponse|TemplateResponse"
    r"|innerHTML|dangerouslySetInnerHTML|iframe"
    r"|secret|token|password|api[_]?key|credential|system_prompt|prompt|instruction"
    r"|@tool|function_tool|register_tool|\btool\b|\bagent\b)",
    re.I,
)
ELLIPSIS_BODY = [ast.Expr(value=ast.Constant(value=Ellipsis))]


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[1:] or list(ELLIPSIS_BODY)
    return body


class _Focus(ast.NodeTransformer):
    def _func(self, node):
        self.generic_visit(node)                      # transform nested defs first
        node.body = _strip_docstring(node.body)
        if not SECURITY.search(ast.unparse(node)):    # nothing security-relevant -> elide body
            node.body = list(ELLIPSIS_BODY)
        return node

    visit_FunctionDef = _func
    visit_AsyncFunctionDef = _func

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        node.body = _strip_docstring(node.body)
        return node

    def visit_Module(self, node):
        self.generic_visit(node)
        node.body = _strip_docstring(node.body)
        return node


class _StripDoc(ast.NodeTransformer):
    def _strip(self, node):
        self.generic_visit(node)
        node.body = _strip_docstring(node.body)
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = visit_Module = _strip


def _line_minify(text: str) -> str:
    out = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].rstrip() if not line.lstrip().startswith("#") else ""
        if stripped:
            out.append(stripped)
    return "\n".join(out)


def reduce(text: str, mode: str = "focus") -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _line_minify(text)
    tree = (_Focus() if mode == "focus" else _StripDoc()).visit(tree)
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree)
    except Exception:
        return _line_minify(text)
