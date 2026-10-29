"""Agent 1b - Threat Model. Turns system_map.json into ranked ATLAS attack paths.

Step 1 (rules, free): five questions asked of the map, one per core family.
  F1  Is user input pasted into a system prompt?             -> direct injection path
  F2  Does a tool return outside content (docs, web, files)?  -> indirect injection path
  F7  Is a sub-agent's output passed back unwrapped?         -> agent-to-agent path
  F6  Is a secret pasted into a prompt?                      -> leakage path
  F3  Can a hijacked agent reach a tool that writes/sends?   -> excessive agency path
Step 2 (optional LLM): re-rate likelihood/impact with a one-line reason.
  The LLM sees only the compact map + the rule threats, and may only use IDs
  that exist in the knowledge base.
Step 3 (free): draw the data-flow diagram (Mermaid) with trust boundaries.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from sentinel import llm
from sentinel.kb import loader
from sentinel.models import SystemMap, Threat

# Tools whose content usually comes from outside the organisation (higher injection risk).
OUTSIDE_SOURCE = ("search", "fetch", "browse", "web", "url", "retriev", "rag", "email_inbox")


def _reachable_tools(m: SystemMap, agent: str, seen: set | None = None) -> set[str]:
    """All tools an agent can trigger, directly or through the agents it calls."""
    seen = seen or set()
    if agent in seen:
        return set()
    seen.add(agent)
    own = next((a.tools for a in m.agents if a.name == agent), [])
    tools = set(own)
    for e in m.edges:
        if e.caller == agent:
            tools |= _reachable_tools(m, e.callee, seen)
    return tools


def rule_threats(m: SystemMap) -> list[Threat]:
    fams = loader.families()
    write_tools = [t.name for t in m.tools if t.effect == "write"]
    callees = {e.callee for e in m.edges}
    roots = [a.name for a in m.agents if a.name not in callees] or [a.name for a in m.agents]
    root_reach = set().union(*(_reachable_tools(m, r) for r in roots)) if roots else set()
    sink = next((t for t in write_tools if t in root_reach), None)
    has_secret = any(p.secret_inside for p in m.prompts)
    readers = {t.name for t in m.tools if t.reads_external_content}
    out: list[Threat] = []

    def add(family, title, atlas, entry, tool, likelihood, impact, reason):
        out.append(Threat(id="", title=title, check_family=family, atlas=atlas, owasp=fams[family]["owasp"],
                          entry_point=entry, tool=tool, likelihood=likelihood, impact=impact, reason=reason))

    for p in m.prompts:                                                        # F1 and F6
        if p.user_input_inside:
            impact = "critical" if sink and has_secret else "high" if sink else "medium"
            add(1, f"User input in system prompt '{p.name}' lets a user hijack the agent",
                ["AML.T0051.000", "AML.T0053", "AML.T0086"], "user_message", sink, "likely",
                impact, f"{p.file}:{p.line} pastes user input into the system prompt")
        if p.secret_inside:
            add(6, f"Secret in prompt '{p.name}' can be extracted",
                ["AML.T0056", "AML.T0057"], "user_message", None, "likely", "high",
                f"{p.file}:{p.line} pastes a secret into the prompt")

    for t in m.tools:                                                          # F2
        if t.reads_external_content:
            outside = any(k in t.name.lower() for k in OUTSIDE_SOURCE)
            add(2, f"Poisoned content returned by '{t.name}' steers the agents",
                ["AML.T0070", "AML.T0051.001", "AML.T0053", "AML.T0086"], "document", t.name,
                "likely" if outside and sink else "possible", "high" if sink else "medium",
                f"{t.file}:{t.line} returns {'outside' if outside else 'internal'} content to the LLM")

    for e in m.edges:                                                          # F7
        if not e.output_wrapped:
            carries_content = bool(_reachable_tools(m, e.callee) & readers)   # can poisoned text flow back?
            add(7, f"'{e.callee}' output is treated as instructions by '{e.caller}'",
                ["AML.T0110.002", "AML.T0080", "AML.T0053"], "agent_message", e.via,
                "likely" if carries_content and sink else "possible", "high" if carries_content else "medium",
                f"{e.file}:{e.line} passes {e.callee} output back unwrapped")

    for name in write_tools:                                                   # F3
        tool = next(t for t in m.tools if t.name == name)
        add(3, f"A hijacked agent abuses '{name}' to exfiltrate data",
            ["AML.T0053", "AML.T0086"], "agent_message", name,
            "likely" if name in root_reach else "possible", "high", f"{tool.file}:{tool.line} has outside effects")

    return out


class Rating(BaseModel):
    index: int
    likelihood: Literal["unlikely", "possible", "likely"]
    impact: Literal["low", "medium", "high", "critical"]
    reason: str


class Ratings(BaseModel):
    ratings: list[Rating]


MAX_LLM_RERATE = 12          # re-rate only the top threats by score - bounds tokens on big maps


def _context(m: SystemMap) -> str:
    """A tiny structural summary for the LLM - NOT the whole map (which can be >100 KB)."""
    writes = sum(t.effect == "write" for t in m.tools)
    entries = [e.get("channel") or e.get("name") for e in m.entry_points][:5]
    return (f"{len(m.agents)} agents, {len(m.tools)} tools ({writes} write), "
            f"{len(m.edges)} agent-to-agent edges; entry points: {entries}")


def refine_with_llm(m: SystemMap, threats: list[Threat], budget: llm.Budget) -> list[Threat]:
    """Re-rate ONLY the top-N threats (by score). Compact context, not the full map, to bound cost."""
    top = threats[:MAX_LLM_RERATE]
    listing = "\n".join(f"{i}. {t.title} | {t.likelihood}/{t.impact}" for i, t in enumerate(top))
    prompt = ("Re-rate each threat's likelihood and impact for this system; one short reason each.\n"
              f"System: {_context(m)}\n\nThreats:\n{listing}")
    answer = llm.ask_json(prompt, Ratings, budget, max_out=1500)
    if answer:
        for r in answer.ratings:
            if 0 <= r.index < len(top):
                threats[r.index] = threats[r.index].model_copy(update=r.model_dump(exclude={"index"}))
    return threats


def build_threat_model(m: SystemMap, budget: llm.Budget | None = None) -> list[Threat]:
    known = loader.ids()
    threats = [t for t in rule_threats(m) if all(a in known for a in t.atlas)]   # drop unknown IDs
    threats.sort(key=lambda t: -t.score)                                         # top-N = highest score
    if budget and llm.enabled():
        threats = refine_with_llm(m, threats, budget)
        threats.sort(key=lambda t: -t.score)                                     # re-sort after re-rating
    return [t.model_copy(update={"id": f"T{i:02d}"}) for i, t in enumerate(threats, 1)]


def mermaid(m: SystemMap) -> str:
    """Data-flow diagram with three trust zones: untrusted input, the app, outside effects."""
    callees = {e.callee for e in m.edges}
    lines = ["flowchart LR", '  subgraph untrusted["Untrusted input"]', "    user([User])"]
    readers = [t for t in m.tools if t.reads_external_content]
    if readers:
        lines.append("    content[(Docs / files / web)]")
    lines += ["  end", '  subgraph app["App process (trust boundary)"]']
    lines += [f"    {a.name}[{a.name} agent]" for a in m.agents]
    lines += [f"    {t.name}{{{{{t.name}}}}}" for t in m.tools if not any(t.name == e.via for e in m.edges)]
    lines += ["  end", '  subgraph outside["Outside effects"]', "    world([Recipients / systems])", "  end"]
    for a in m.agents:
        if a.name not in callees:
            lines.append(f"  user -->|request| {a.name}")
    for e in m.edges:
        lines.append(f"  {e.caller} -->|{e.via}| {e.callee}")
    for a in m.agents:
        for t in a.tools:
            if not any(t == e.via for e in m.edges):
                lines.append(f"  {a.name} --> {t}")
    for t in readers:
        lines.append(f"  content -.->|returned to LLM| {t.name}")
    for t in m.tools:
        if t.effect == "write":
            lines.append(f"  {t.name} --> world")
    return "\n".join(lines)


def to_markdown(m: SystemMap, threats: list[Threat]) -> str:
    names = loader.ids()
    rows = "\n".join(
        f"| {t.id} | {t.title} | {' → '.join(f'{a} {names[a]}' for a in t.atlas)} | {', '.join(t.owasp)} "
        f"| {t.likelihood} | {t.impact} | {t.score} |" for t in threats)
    return (f"# Threat model: {m.target}\n\n## Data flow\n\n```mermaid\n{mermaid(m)}\n```\n\n"
            "## Ranked attack paths (MITRE ATLAS v2026.09)\n\n"
            "| ID | Threat | ATLAS path | OWASP 2026 | Likelihood | Impact | Score |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n" + rows + "\n")
