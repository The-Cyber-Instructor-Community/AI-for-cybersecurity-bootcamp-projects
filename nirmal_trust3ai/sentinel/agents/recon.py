"""Agent 1a - Recon. Builds a map of the target AI app from its source code.

No LLM is used here: Python's `ast` module reads the code and finds
  * LLM calls            (client.messages.create, llm.complete, ...)
  * prompts              (and which variables are pasted into them)
  * tools                (and whether they read or write)
  * agents               (and which tools each one has)
  * agent-to-agent edges (an agent's tool that runs another agent)
  * entry points         (where outside input arrives)
The result, system_map.json, is small - so the threat-model LLM step reads
the map, never the whole repo. That is the main token saving.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from sentinel.models import AgentEdge, AgentInfo, PromptInfo, SystemMap, ToolInfo

USER_VAR = re.compile(r"(?i)(user|message|query|question|request|input)")
SECRET_VAR = re.compile(r"(?i)(password|secret|token|api_?key|credential)")
PROMPT_NAME = re.compile(r"(?i)(prompt|system|instruction)")
TOOL_FACTORY = re.compile(r"(?i)^(spec|tool|make_tool|function_tool)$")
TOOL_DECORATOR = re.compile(r"(?i)(^|\.)(tool|function_tool|register_tool|ai_function|action|command)s?$")
ENTRY_NAME = re.compile(r"(?i)^(handle|chat|respond|answer|invoke|main)$")
WRITE_CALL = re.compile(r"(?i)(post|send|sendmail|remove|unlink|delete|rmtree|write|system|run|popen|put|patch)$")
READ_CALL = re.compile(r"(?i)(read_text|read|get|load|fetch|query|search)$")
LLM_CALL = re.compile(r"(\.messages\.create|\.chat\.completions\.create|\.complete|\.invoke|\.generate_content)$")
HTTP_POST = re.compile(r"\.(post|stream)$")                        # raw HTTP (httpx/requests/aiohttp)
LLM_URL = re.compile(r"(?i)(/v1/chat|/api/chat|/api/generate|/completions|:11434|openai|anthropic|ollama|generativelanguage)")
SKIP_DIRS = {"tests", "test", ".venv", "venv", "sandbox", "__pycache__"}


def _name(node: ast.AST) -> str:
    """Last part of a call target: `self.client.messages.create` -> `create`."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _fstring_vars(node: ast.JoinedStr) -> list[str]:
    return [ast.unparse(v.value) for v in node.values if isinstance(v, ast.FormattedValue)]


def _first_str(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


class _FileVisitor(ast.NodeVisitor):
    def __init__(self, rel: str):
        self.rel = rel
        self.llm_calls, self.prompts, self.tool_names, self.functions = [], [], [], {}
        self.agents, self.agent_attrs, self.delegations, self.entries = [], {}, [], []
        self.owners = {}                              # "self.ask_researcher" -> "orchestrator"

    # -- functions: prompts built by functions, entry points, delegation, tool bodies
    def visit_FunctionDef(self, fn: ast.FunctionDef) -> None:
        self.functions[fn.name] = fn
        for dec in fn.decorator_list:                 # @tool / @function_tool / @agent.tool ...
            name = _name(dec.func) if isinstance(dec, ast.Call) else _name(dec)
            if TOOL_DECORATOR.search(name) or TOOL_DECORATOR.search(ast.unparse(dec)):
                self.tool_names.append(fn.name)
                break
        params = [a.arg for a in fn.args.args if a.arg != "self"]
        if PROMPT_NAME.search(fn.name):
            for ret in ast.walk(fn):
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.JoinedStr):
                    used = _fstring_vars(ret.value)
                    self.prompts.append(PromptInfo(
                        name=fn.name, file=self.rel, line=fn.lineno, interpolates=used,
                        user_input_inside=any(v in params and USER_VAR.search(v) for v in used),
                        secret_inside=any(SECRET_VAR.search(v) for v in used)))
        if ENTRY_NAME.match(fn.name) and any(USER_VAR.search(p) for p in params):
            self.entries.append({"name": fn.name, "file": self.rel, "line": fn.lineno, "channel": "user_message"})
        for node in ast.walk(fn):                     # self.<agent>.run(...) inside a method = delegation
            if (isinstance(node, ast.Call) and _name(node.func) == "run"
                    and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Attribute)):
                wrapped = any(isinstance(c, ast.Constant) and "untrusted" in str(c.value) for c in ast.walk(fn)) \
                    or any(isinstance(c, ast.Attribute) and c.attr == "model_validate" for c in ast.walk(fn))
                self.delegations.append((fn.name, node.func.value.attr, fn.lineno, wrapped))
        self.generic_visit(fn)

    # -- assignments: prompt constants and `self.x = Agent("x", ...)`
    def visit_Assign(self, node: ast.Assign) -> None:
        target = node.targets[0]
        tname = ast.unparse(target)
        if PROMPT_NAME.search(tname) and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
            used = _fstring_vars(node.value) if isinstance(node.value, ast.JoinedStr) else []
            self.prompts.append(PromptInfo(name=tname, file=self.rel, line=node.lineno, interpolates=used,
                                           secret_inside=any(SECRET_VAR.search(v) for v in used)))
        if isinstance(node.value, ast.Call) and _name(node.value.func).endswith("Agent") and isinstance(target, ast.Attribute):
            if (agent := _first_str(node.value)):
                self.agent_attrs[target.attr] = agent
        self.generic_visit(node)

    # -- calls: LLM calls, tool definitions, agent construction
    def visit_Call(self, call: ast.Call) -> None:
        func = ast.unparse(call.func)
        if LLM_CALL.search("." + func.split(".", 1)[-1] if "." in func else func):
            self.llm_calls.append({"file": self.rel, "line": call.lineno, "call": func})
        elif HTTP_POST.search("." + _name(call.func)):               # raw HTTP that looks like an LLM call
            blob = ast.unparse(call)
            has_messages = '"messages"' in blob or "'messages'" in blob or "messages=" in blob
            if has_messages and (LLM_URL.search(blob) or "json=" in blob):   # a chat payload, not a web route
                self.llm_calls.append({"file": self.rel, "line": call.lineno, "call": func + " (http)"})
        if TOOL_FACTORY.match(_name(call.func)) and (name := _first_str(call)):
            self.tool_names.append(name)
        if _name(call.func).endswith("Agent") and (name := _first_str(call)):
            prompt = ast.unparse(call.args[1]) if len(call.args) > 1 else None
            tools = []
            for arg in call.args:
                if isinstance(arg, ast.Dict):
                    tools = [k.value for k in arg.keys if isinstance(k, ast.Constant)]
                    self.owners.update({ast.unparse(v): name for v in arg.values})
            self.agents.append(AgentInfo(name=name, file=self.rel, line=call.lineno, prompt=prompt, tools=tools))
        self.generic_visit(call)


def _tool_effect(fn: ast.FunctionDef) -> tuple[str, bool]:
    """Classify a tool function as read or write, and whether it returns outside content."""
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    opens_for_write = any(_name(c.func) == "open" and any(
        isinstance(a, ast.Constant) and str(a.value)[:1] in "aw" for a in c.args[1:]) for c in calls)
    writes = opens_for_write or any(WRITE_CALL.search(_name(c.func)) for c in calls if _name(c.func) != "run")
    reads = any(READ_CALL.search(_name(c.func)) for c in calls)
    returns_content = any(isinstance(r, ast.Return) and r.value is not None and any(
        isinstance(c, ast.Call) and READ_CALL.search(_name(c.func)) for c in ast.walk(r.value)) for r in ast.walk(fn))
    effect = "write" if writes else "read" if reads else "unknown"
    return effect, returns_content


def build_system_map(target_dir: str | Path) -> SystemMap:
    root = Path(target_dir)
    files = [p for p in sorted(root.rglob("*.py")) if not SKIP_DIRS & set(p.relative_to(root).parts)]
    visitors = []
    for path in files:
        v = _FileVisitor(str(path.relative_to(root)))
        v.visit(ast.parse(path.read_text(), filename=str(path)))
        visitors.append(v)

    functions = {name: (v.rel, fn) for v in visitors for name, fn in v.functions.items()}
    owners = {k: a for v in visitors for k, a in v.owners.items()}
    attr_to_agent = {k: a for v in visitors for k, a in v.agent_attrs.items()}

    tool_names = dict.fromkeys(n for v in visitors for n in v.tool_names)    # unique, in order
    tools = []
    for name in tool_names:
        if name in functions:
            rel, fn = functions[name]
            effect, external = _tool_effect(fn)
            tools.append(ToolInfo(name=name, file=rel, line=fn.lineno, effect=effect, reads_external_content=external))

    edges = []
    for v in visitors:
        for via, attr, line, wrapped in v.delegations:
            caller = owners.get(f"self.{via}", "unknown")
            edges.append(AgentEdge(caller=caller, callee=attr_to_agent.get(attr, attr), via=via,
                                   file=v.rel, line=line, output_wrapped=wrapped))

    return SystemMap(
        target=str(root), files=[str(p.relative_to(root)) for p in files],
        llm_calls=[c for v in visitors for c in v.llm_calls],
        prompts=[p for v in visitors for p in v.prompts],
        tools=tools,
        agents=[a for v in visitors for a in v.agents],
        edges=edges,
        entry_points=[e for v in visitors for e in v.entries],
    )
