"""
Triage Agent — the reasoning-heavy step.

Loads the composed triage playbook(s) for the alert's technique(s), walks the
investigation via a Claude tool-use loop over the enrichment tools, weighs the
findings against the playbook's guidance (and any retrieved RAG examples), and
returns a structured verdict: {verdict, confidence, rationale, key_findings}.

Behaviour is driven by the editable playbook markdown, not hardcoded here.
"""

from __future__ import annotations

import json

from common import (CaseContext, compose_playbooks, claude_tool_loop,
                    extract_json, TRIAGE_MODEL)
from tools import macos_tools, vt_client, wazuh_client

# --------------------------------------------------------------------------- #
# Tool schemas exposed to the model (names match the playbook frontmatter)
# --------------------------------------------------------------------------- #

TOOLS = [
    {"name": "read_plist", "description": "Parse a LaunchAgent/Daemon plist; returns Program, ProgramArguments, RunAtLoad, KeepAlive.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "read_text_file", "description": "Read a text file (e.g. a shell startup file like ~/.zshrc) to inspect its contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "check_signature", "description": "Code-signing status of a binary/bundle (apple_signed / developer_id_signed / unsigned / adhoc).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "hash_and_vt_lookup", "description": "SHA-256 a file and look up its VirusTotal reputation (hash only).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "path_reputation", "description": "Heuristic on a file location (/tmp, /Users/Shared, hidden, etc.).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "get_process_info", "description": "Parent process + command line for a running process (by name or PID).",
     "input_schema": {"type": "object", "properties": {"name_or_pid": {"type": "string"}}, "required": ["name_or_pid"]}},
    {"name": "get_network_connections", "description": "Established network connections for a numeric PID.",
     "input_schema": {"type": "object", "properties": {"pid": {"type": "string"}}, "required": ["pid"]}},
    {"name": "query_host_history", "description": "Has this file path / hash been seen on this host before?",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "sha256": {"type": "string"}}}},
]


def _make_dispatch(case: CaseContext):
    def dispatch(name: str, inp: dict):
        if name == "read_plist":
            return macos_tools.read_plist(inp["path"])
        if name == "read_text_file":
            return macos_tools.read_text_file(inp["path"])
        if name == "check_signature":
            return macos_tools.check_signature(inp["path"])
        if name == "hash_and_vt_lookup":
            h = macos_tools.sha256_file(inp["path"])
            if not h.get("sha256"):
                return h
            return {"hash": h, "virustotal": vt_client.vt_lookup(h["sha256"])}
        if name == "path_reputation":
            return macos_tools.path_reputation(inp["path"])
        if name == "get_process_info":
            return macos_tools.get_process_info(inp["name_or_pid"])
        if name == "get_network_connections":
            return macos_tools.get_network_connections(inp["pid"])
        if name == "query_host_history":
            return wazuh_client.query_host_history(
                case.agent_name, path=inp.get("path"), sha256=inp.get("sha256"))
        return {"error": f"unknown tool {name}"}
    return dispatch


def _rag_examples(case: CaseContext) -> str:
    """RAG hook — retrieve similar labeled cases. Filled in P1 (Chroma)."""
    try:
        from rag import retrieve_similar  # optional; present after P1
        examples = retrieve_similar(case)
        if examples:
            return "## Similar past cases I already labeled (mirror this reasoning)\n" + examples
    except Exception:
        pass
    return "## Similar past cases\n(none retrieved yet)"


SYSTEM_WRAPPER = (
    "You are the triage agent in an automated macOS SOC. Follow the playbook "
    "instruction(s) below exactly — they are analyst-authored and may be edited. "
    "Use the provided tools to investigate; do not invent findings. When done, "
    "output ONLY a JSON object: {\"verdict\":\"malicious|ambiguous|benign\","
    "\"confidence\":0-100,\"rationale\":\"...\",\"key_findings\":{...}}."
)


def triage(case: CaseContext) -> CaseContext:
    playbooks = compose_playbooks(case.techniques, "triage")
    if not playbooks:
        case.triage = {"verdict": "ambiguous", "confidence": 50,
                       "rationale": "no triage playbook for technique(s)", "key_findings": {}}
        return case

    # Compose the (possibly multiple) playbook bodies + RAG context.
    body = "\n\n".join(f"# PLAYBOOK — {p.technique}\n{p.body}" for p in playbooks)
    if len(playbooks) > 1:
        body += ("\n\n# MULTI-TECHNIQUE ALERT\nSynthesize ONE investigation across "
                 "the playbooks above; do overlapping steps once; prioritize by severity.")

    rag_block = _rag_examples(case)
    n_rag = rag_block.count("(similarity")
    if n_rag:
        print(f"   RAG: injected {n_rag} similar labeled case(s) into the triage prompt", flush=True)
    system = f"{SYSTEM_WRAPPER}\n\n{body}\n\n{rag_block}"
    prompt = (
        f"Alert to triage:\n{json.dumps(case.alert, indent=2)}\n\n"
        f"Technique(s): {', '.join(case.techniques)}\n"
        "Investigate with the tools, then output the JSON verdict."
    )

    text, trace = claude_tool_loop(
        model=TRIAGE_MODEL, system=system, prompt=prompt,
        tools=TOOLS, dispatch=_make_dispatch(case))

    verdict = extract_json(text)
    if not verdict:
        verdict = {"verdict": "ambiguous", "confidence": 50,
                   "rationale": text[:500] or "no structured verdict", "key_findings": {}}
    threshold = playbooks[0].confidence_threshold
    verdict["threshold"] = threshold
    verdict["actionable"] = (
        verdict.get("verdict") == "malicious"
        and int(verdict.get("confidence", 0)) >= threshold
    ) or verdict.get("verdict") == "ambiguous"

    verdict["rag_count"] = n_rag
    case.triage = verdict
    case.enrichment = {"tool_trace": trace}
    return case


if __name__ == "__main__":
    import sys
    from common import techniques_for_alert
    alert = json.load(open(sys.argv[1] if len(sys.argv) > 1
                           else "data/sample_alerts/d1_launchagent.json"))
    c = CaseContext(alert=alert, techniques=techniques_for_alert(alert))
    c = triage(c)
    print(json.dumps(c.triage, indent=2))
    print(f"\n[{len(c.enrichment.get('tool_trace', []))} tool calls]")
