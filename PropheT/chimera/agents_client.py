"""Run the LangFlow agents for one case, or stand in for them.

LangFlow mode: POST {LANGFLOW_URL}/api/v1/run/{LANGFLOW_FLOW_ID} with the case ID as the chat
input, collect every message text in the response, and sort them into the analysts' text (the
second Chat Output, on the orchestrator) and the report (the last Chat Output). Every run gets a
session of its own: without one LangFlow uses the flow ID as the session, so the agents' chat memory
carried earlier cases into later ones (Oct 19: case_004's analysts quoted case_005's evidence).

Mock mode (CHIMERA_MOCK_FLOW=1, or no flow configured): write both texts in code from the
evidence lines, in the exact formats Bundle Check and Evidence Check expect. The output says it
is a mock. It exists so the console works before the flow is wired, and as the no-model fallback.
"""

import json
import re
import uuid

import httpx

from .checks import bundle_check, tidy_committee_text
from .schema import FAMILIES

MOCK_NOTE = "(Mock flow: written by code from the evidence lines. The LangFlow agents did not run.)"


# ---------------------------------------------------------------- mock flow

def quotable(text: str, limit: int = 90) -> str:
    """A verbatim piece of an evidence line that contains no quote marks, cut at a word boundary."""
    parts = [p.strip(" .,:;") for p in re.split(r'["“”]', text)]
    best = max(parts, key=len) if parts else text
    if len(best) > limit:
        best = best[:limit].rsplit(" ", 1)[0]
    return best.strip(" .,:;")


def _bullet(sig: dict) -> list[str]:
    fam = sig["family"]
    return [f"- {sig['text']}", f"  Evidence: {sig['evidence_id']} \"{quotable(sig['text'])}\" [{fam}]"]


def mock_flow(evidence: dict) -> dict:
    """Analysts' text, orchestrator notes and a report, all from the evidence bundle."""
    case_id = evidence["case_id"]
    signals = evidence["signals"]
    by_family = {fam: [s for s in signals if s["family"] == fam] for fam in FAMILIES}

    analysts = []
    for fam in FAMILIES:
        scored = [s for s in by_family[fam] if s["points"] > 0]
        info = [s for s in by_family[fam] if s["points"] == 0]
        block = [f"ANALYST {fam} REPORT", f"Case: {case_id}"]
        if scored:
            block.append("Findings:")
            for s in scored:
                block += _bullet(s)
        else:
            block.append("Findings: none scored.")
        limits = " ".join(s["text"] for s in info) or "none stated."      # the analyst prompts' rule
        block += [f"Limits: {limits}", "STATUS: COMPLETE", ""]
        analysts += block

    if evidence.get("contradictions"):
        # Since Oct 23 the bundle carries the section code wrote; the Reporter copies it, so the mock does too.
        contradiction = "\n".join(f"- {line}" for line in evidence["contradictions"])
    else:                                                 # an evidence.json from before Oct 23
        hit = [fam for fam in FAMILIES if any(s["points"] > 0 for s in by_family[fam])]
        ids = "; ".join(s["evidence_id"] for fam in hit for s in by_family[fam] if s["points"] > 0)
        if len(hit) >= 2:
            contradiction = (f"- None found between families. The {' and '.join(FAMILIES[f].lower() for f in hit)} "
                             f"evidence points the same way ({ids}).")
        elif hit:
            contradiction = f"- Only the {FAMILIES[hit[0]].lower()} family produced scored evidence, so there is nothing to cross-check."
        else:
            contradiction = "- No family produced scored evidence."
    analysts += ["ORCHESTRATOR NOTES", "Contradictions: written by code." if evidence.get("contradictions") else "Contradictions:",
                 *([] if evidence.get("contradictions") else [contradiction]),
                 "DISPATCH LOG: " + ", ".join(FAMILIES), MOCK_NOTE]
    analysts_text = "\n".join(analysts)

    report = [evidence["critical_line"], evidence["score_line"], ""]
    for fam, label in FAMILIES.items():
        report.append(f"## [{fam}] {label}")
        scored = [s for s in by_family[fam] if s["points"] > 0]
        if scored:
            for s in scored:
                report += _bullet(s)
        else:
            report.append("No scored evidence.")
        report.append("")
    bundle = bundle_check(evidence_md_from(evidence), analysts_text)
    problems = [l for l in bundle.splitlines() if l.startswith("- ") and l != "- none"]
    report += ["## Contradictions", contradiction, "",
               "## Checks", "- Bundle Check: " + ("no problems." if not problems else f"{len(problems)} problem(s), see the Checks panel."),
               "", "Decision support only. A person makes the final call.", MOCK_NOTE]
    return {"mode": "mock", "analysts": analysts_text, "report": "\n".join(report)}


def evidence_md_from(evidence: dict) -> str:
    """Rebuild the evidence.md text from evidence.json (same lines as bundle.render_md)."""
    lines = [f"# Evidence bundle: {evidence['case_id']}", ""]
    for fam, label in FAMILIES.items():
        lines.append(f"## [{fam}] {label}")
        fam_lines = []
        for s in evidence["signals"]:
            if s["family"] != fam:
                continue
            weight = f"{s['strength']}, {s['points']} pt{'s' if s['points'] != 1 else ''}" if s["points"] else "info"
            fam_lines.append(f"- {s['evidence_id']} ({weight}) {s['text']}")
        lines += fam_lines or ["- (no evidence lines)"]
        lines.append("")
    lines += ["## Code score", f"- {evidence['critical_line']}", f"- {evidence['score_line']}", ""]
    if evidence.get("contradictions"):                    # since Oct 23
        lines += ["## Contradictions (code)", *(f"- {line}" for line in evidence["contradictions"]), ""]
    return "\n".join(lines)


# ------------------------------------------------------------- LangFlow mode

def flow_configured(settings) -> bool:
    return bool(settings.langflow_url and settings.langflow_flow_id) and not settings.mock_flow


def _collect_texts(obj, found: list, name: str = "") -> None:
    """Walk LangFlow's response and collect every message text, with the component name if present."""
    if isinstance(obj, dict):
        name = obj.get("component_display_name") or obj.get("display_name") or name
        for key in ("text", "message"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                found.append((name, val.strip()))
        for val in obj.values():
            _collect_texts(val, found, name)
    elif isinstance(obj, list):
        for val in obj:
            _collect_texts(val, found, name)


def sort_outputs(texts: list[tuple[str, str]]) -> dict:
    """Pick the analysts' text and the report out of whatever the flow returned."""
    seen, unique = set(), []
    for name, text in texts:
        if text not in seen:
            seen.add(text)
            unique.append((name, text))
    analysts = [t for _, t in unique if "ANALYST A1 REPORT" in t or "DISPATCH LOG" in t]
    reports = [t for _, t in unique if "CODE SCORE:" in t and "## [" in t]
    return {
        # LangFlow repeats each analyst's report inside the Orchestrator's message; show one copy.
        "analysts": tidy_committee_text(max(analysts, key=len)) if analysts else "",
        "report": max(reports, key=len) if reports else "",
        "texts": [{"component": n, "text": t} for n, t in unique],
    }


def new_session(case_id: str) -> str:
    """A LangFlow session ID used once: the case ID and a random part."""
    return f"chimera-{case_id}-{uuid.uuid4().hex[:12]}"


def run_flow(settings, case_id: str, log=print) -> dict:
    url = f"{settings.langflow_url.rstrip('/')}/api/v1/run/{settings.langflow_flow_id}"
    headers = {"Content-Type": "application/json"}
    if settings.langflow_api_key:
        headers["x-api-key"] = settings.langflow_api_key
    session = new_session(case_id)              # fresh chat memory for every run (see the module docstring)
    payload = {"input_value": case_id, "input_type": "chat", "output_type": "chat", "session_id": session}
    log(f"POST {url} (case {case_id}, session {session}); the 30B can take a few minutes")
    with httpx.Client(timeout=settings.langflow_timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    raw = resp.json()
    found: list = []
    _collect_texts(raw, found)
    sorted_out = sort_outputs(found)
    log(f"flow returned {len(sorted_out['texts'])} message text(s); analysts {'found' if sorted_out['analysts'] else 'NOT found'}, "
        f"report {'found' if sorted_out['report'] else 'NOT found'}")
    return {"mode": "langflow", "raw": raw, "session_id": session, **sorted_out}


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)
