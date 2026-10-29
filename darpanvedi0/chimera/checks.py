"""Hard checks on agent output, copied from the Assignment 2 pattern.

Bundle Check:   did each analyst report, finish, and cite real evidence from its
                own family? Which scored evidence lines did nobody cite?
Evidence Check: is every "Evidence:" line in the final report a real ID, under
                the right [A1]-[A3] tag, with a quote that appears verbatim?
                Did the Reporter copy the two code lines unchanged?

A passing Evidence Check proves the quotes are real. It does not prove the
sentences around them are right (Assignment 2: 27/27 quotes verified, five
sentences still wrong).

Since Oct 18 both checks also flag any evidence ID named anywhere (the
Orchestrator's contradictions, the report's) that is not in the bundle, and the
Evidence Check flags scored evidence the report leaves out and names each
finding that has no Evidence: line. "No scored evidence." is not a finding,
with or without a bullet.

Chimera's output goes only to the hiring team: the candidate never gets any
signal from it (the author, Oct 18). So neither the Orchestrator's notes nor the
report may hold questions for the candidate, and both checks flag a questions
section. (Before that decision, four runs had agents writing questions that
named the watchlist, invented a date discrepancy and hinted at the email check.)

Since Oct 19 both checks also read the Contradictions section. A contradiction
must cite two evidence lines, and a "point the same way" sentence must cite
scored lines from at least two families and no info line. On the first pass-rate
run with a fresh session per case, the Orchestrator copied its prompt's example
"(E1.2; E3.1)" or adapted it to cite "No interview recording" (an info line),
and listed one line's own comparison (claimed experience against account age)
as a contradiction.

Also since Oct 19, both checks flag an email, watchlist row, ring, phone number,
IP address or profile that this case's evidence does not contain. With the shared
chat memory, case_005's email reached case_004's report in a finding sentence,
outside any quote, where no other check would have seen it.
"""

import re

from .schema import FAMILIES

EVIDENCE_LINE = re.compile(r"^- (E([1-3])\.\d+) \(([^)]*)\) (.*)$", re.M)
REPORT_BLOCK = re.compile(r"ANALYST (A[1-3]) REPORT(.*?)(?=ANALYST A[1-3] REPORT|ORCHESTRATOR NOTES|\Z)", re.S)
CITATION = re.compile(r"\bE([1-3])\.(\d+)\b")
# A citation: Evidence: <ID> "quote" [A#]. The quote group is optional here so that a citation written without one
# is still recognised as a citation and reported for it (Oct 23 review, findings 4 and 14), rather than passing
# as verified (before) or vanishing into "scored evidence left out".
REPORT_EVIDENCE = re.compile(r"Evidence:\s*(E([1-3])\.\d+)\s*(?:[\"“]([^\"”]*)[\"”])?\s*\[(A[1-3])\]")
EVIDENCE_MENTION = re.compile(r"^.*\bEvidence:.*$", re.M)        # every line that says Evidence:, parsable or not
MIN_QUOTE_CHARS = 8                                                # "R-006" or "US" proves nothing; a clause does
CODE_LINE_PREFIXES = ("MOST CRITICAL FINDING:", "CODE SCORE:")

# A section of questions for the candidate: a heading that says questions ("## Questions for the candidate") or a
# label line ("Follow-up questions:"). A sentence that happens to start with the word is not a section (finding 15).
QUESTIONS_SECTION = re.compile(r"^[ \t]*(?:#+[ \t]*(?:follow-up |interview |suggested )?questions\b.*"
                               r"|(?:follow-up |interview |suggested )?questions(?: for the candidate| to ask)?[ \t]*:.*)$",
                               re.I | re.M)

# What the Reporter writes under a family heading with no scored findings. It is not a finding, so it
# needs no Evidence: line, bullet or not. (The prompt asks for plain text; on Oct 18 qwen3-coder wrote
# "- No scored evidence." and the check counted it as a finding without evidence.)
NO_FINDINGS = re.compile(r"^(?:no scored evidence|no scored findings|no findings|none)\.?$", re.I)

# Identifiers code can compare with the bundle: emails, watchlist rows and rings, E.164 phone numbers, IPv4
# addresses, LinkedIn and GitHub profiles. One in the agents' text that is not in this case's evidence came from
# somewhere else: another case (Oct 19: a shared chat memory put case_005's email into case_004's finding
# sentence, outside any quote) or the model.
IDENTIFIER = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\bW-\d{4}\b|\bR-\d{3}\b|\+\d{10,15}\b"
                        r"|\b(?:\d{1,3}\.){3}\d{1,3}\b|\b(?:linkedin\.com/in|github\.com)/[\w-]+")

# The Contradictions section: "Contradictions:" in the Orchestrator's notes, "## Contradictions" in the report.
CONTRADICTIONS = re.compile(r"^[ \t]*(?:#+[ \t]*)?Contradictions[ \t]*(?::[ \t]*(.*?))?[ \t]*$", re.I | re.M)
NONE_FOUND = re.compile(r"^(?:none found|none|no contradictions)\b", re.I)
SAME_WAY = re.compile(r"\bpoints? the same way\b", re.I)


def _id_key(eid: str) -> tuple[int, int]:
    fam, num = eid[1:].split(".")
    return int(fam), int(num)


def tidy_committee_text(text: str) -> str:
    """One copy of each analyst report, then the Orchestrator's notes.

    LangFlow 1.12 adds every nested agent's answer to the parent agent's message, so the
    Orchestrator's output holds each report twice: the analyst's own (glued to the next one with no
    line break) and the Orchestrator's copy. The checks can read both; for display, keep the last
    copy of each report, each on its own lines, in A1-A3 order. Text with one copy of each report,
    each starting on its own line, comes back unchanged.
    """
    matches = list(REPORT_BLOCK.finditer(text))
    fams = [m.group(1) for m in matches]
    glued = any(m.start() > 0 and text[m.start() - 1] != "\n" for m in matches)
    if len(fams) == len(set(fams)) and not glued:
        return text
    last = {m.group(1): m.group(2) for m in matches}
    parts = [f"ANALYST {fam} REPORT{last[fam].rstrip()}" for fam in FAMILIES if fam in last]
    notes = text.rfind("ORCHESTRATOR NOTES")
    if notes != -1:
        parts.append(text[notes:].strip())
    return "\n".join(parts)


def candidate_questions(text: str) -> bool:
    """True when the text has a questions section. Chimera's output never addresses the candidate."""
    return bool(QUESTIONS_SECTION.search(text))


def foreign_identifiers(evidence_md: str, text: str) -> list[str]:
    """Emails, watchlist rows, rings, phones, IPs and profiles in the text that the case's evidence does not contain."""
    return sorted({i for i in IDENTIFIER.findall(text) if i not in evidence_md})


def _contradiction_lines(text: str) -> list[str]:
    """The lines of each Contradictions section, without bullets; a section ends at a heading or a new label."""
    out = []
    for m in CONTRADICTIONS.finditer(text):
        rest = [m.group(1) or ""] + text[m.end():].splitlines()[1:]
        for line in rest:
            s = line.strip()
            if s.startswith(("#", "DISPATCH LOG", "ANALYST A", "ORCHESTRATOR NOTES", "Decision support only")) \
                    or (s.endswith(":") and not s.startswith("- ")):
                break
            body = s.removeprefix("- ").strip()
            if body:
                out.append(body)
    return list(dict.fromkeys(out))


def contradiction_problems(text: str, lines: dict) -> list[str]:
    """A contradiction cites two evidence lines; "point the same way" cites scored lines from two families.

    IDs that are not in the bundle are left to the stray-ID problem, so a line naming one is not judged here.
    """
    problems = []
    for body in _contradiction_lines(text):
        ids = list(dict.fromkeys(f"E{a}.{b}" for a, b in CITATION.findall(body)))
        if any(i not in lines for i in ids):
            continue
        if SAME_WAY.search(body):
            info = [i for i in ids if not lines[i]["scored"]]
            families = {lines[i]["family"] for i in ids if lines[i]["scored"]}
            if not ids:
                problems.append('"Point the same way" cites no evidence IDs.')
            elif info:
                problems.append(f'"Point the same way" cites an info line, which is not a finding: {", ".join(info)}.')
            elif len(families) < 2:
                problems.append(f'"Point the same way" needs scored findings from two families: {", ".join(ids)}.')
        elif not NONE_FOUND.match(body) and len(ids) == 1:          # no ID: a remark such as "nothing to cross-check"
            problems.append(f"A contradiction cites one evidence line ({ids[0]}); "
                            "a contradiction is two lines that cannot both be true.")
    return problems


def code_contradictions(evidence_md: str) -> list[str] | None:
    """The lines of the bundle's "## Contradictions (code)" section, without bullets; None for a bundle from before
    Oct 23, which has no such section (the Orchestrator wrote its own then, and the checks judge those as before)."""
    m = re.search(r"^## Contradictions \(code\)\s*$(.*?)(?=^## |\Z)", evidence_md, flags=re.M | re.S)
    if not m:
        return None
    return [l.strip().removeprefix("- ").strip() for l in m.group(1).splitlines() if l.strip()]


def _same_text(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def parse_bundle(evidence_md: str) -> dict:
    lines = {}
    for m in EVIDENCE_LINE.finditer(evidence_md):
        eid, digit, weight, text = m.groups()
        lines[eid] = {"family": f"A{digit}", "weight": weight, "scored": weight != "info", "text": text}
    return lines


def code_lines(evidence_md: str) -> list[str]:
    out = []
    for line in evidence_md.splitlines():
        stripped = line.removeprefix("- ").strip()
        if stripped.startswith(CODE_LINE_PREFIXES):
            out.append(stripped)
    return out


def bundle_check(evidence_md: str, analyst_text: str) -> str:
    lines = parse_bundle(evidence_md)
    blocks: dict = {}
    for m in REPORT_BLOCK.finditer(analyst_text):
        blocks[m.group(1)] = blocks.get(m.group(1), "") + m.group(2)

    rows = ["| Analyst | Report found | STATUS: COMPLETE | Lines cited | Scored lines not cited |",
            "|---|---|---|---|---|"]
    problems = []
    for fam, label in FAMILIES.items():
        block = blocks.get(fam)
        if block is None:
            rows.append(f"| {fam} {label} | no | no | 0 | n/a |")
            problems.append(f"{fam} {label}: report missing.")
            continue
        complete = "STATUS: COMPLETE" in block
        cited = {f"E{a}.{b}" for a, b in CITATION.findall(block)}
        unknown = sorted(c for c in cited if c not in lines)
        other = sorted(c for c in cited if c in lines and lines[c]["family"] != fam)
        uncited = [i for i, info in lines.items() if info["family"] == fam and info["scored"] and i not in cited]
        rows.append(f"| {fam} {label} | yes | {'yes' if complete else 'no'} | {len(cited)} | "
                    f"{', '.join(uncited) or 'none'} |")
        if not complete:
            problems.append(f"{fam} {label}: no 'STATUS: COMPLETE' line.")
        if unknown:
            problems.append(f"{fam} {label}: cites IDs that are not in the bundle: {', '.join(unknown)}.")
        if other:
            problems.append(f"{fam} {label}: cites another family's evidence: {', '.join(other)}.")
        for i in uncited:
            problems.append(f"{fam} {label}: did not cite {i} ({lines[i]['weight']}).")
    notes_at = analyst_text.rfind("ORCHESTRATOR NOTES")
    if notes_at != -1:
        named = {f"E{a}.{b}" for a, b in CITATION.findall(analyst_text[notes_at:])}
        stray = sorted(named - set(lines), key=_id_key)
        if stray:
            problems.append(f"The Orchestrator's notes name IDs that are not in the bundle: {', '.join(stray)}.")
        problems += [f"The Orchestrator's notes: {p}" for p in contradiction_problems(analyst_text[notes_at:], lines)]
    foreign = foreign_identifiers(evidence_md, analyst_text)
    if foreign:
        problems.append(f"The committee's text names {', '.join(foreign)}, which this case's evidence does not contain.")
    if candidate_questions(analyst_text):
        problems.append("The Orchestrator wrote questions for the candidate. Chimera's output goes only to the hiring "
                        "team, so its prompt is out of date.")

    out = ["BUNDLE CHECK (code)", "", *rows, "", "BUNDLE PROBLEMS / COVERAGE GAPS"]
    out += [f"- {p}" for p in problems] or ["- none"]
    written = code_contradictions(evidence_md)
    if written is not None:
        # The Reporter's one input besides the Orchestrator's output: the section code wrote, to copy (Oct 23).
        out += ["", "CONTRADICTIONS (written by code; the Reporter copies these lines under ## Contradictions)"]
        out += [f"- {line}" for line in written]
    return "\n".join(out)


def _findings_without_evidence(report: str) -> list[tuple[str, str]]:
    """Bullets under an [A1]-[A3] heading must be followed by an Evidence: line.

    Returns (family, bullet text) for each bullet that isn't, so the problem can name it.
    """
    missing, family = [], None
    lines = report.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#"):
            m = re.search(r"\[(A[1-3])\]", line)
            family = m.group(1) if m else None
            continue
        text = line.strip()
        if not family or not text.startswith("- ") or "Evidence:" in text:
            continue
        body = text[2:].strip()
        if NO_FINDINGS.match(body):
            continue
        # The citation is the next non-blank line and it starts with Evidence:. A later bullet's citation, or a
        # sentence that mentions the word, does not cover this finding (Oct 23 review, finding 5).
        nxt = next((l for l in lines[i + 1:] if l.strip()), "")
        if not nxt.strip().startswith("Evidence:"):
            missing.append((family, body[:80]))
    return missing


def unparsable_citations(report: str) -> list[str]:
    """Lines that say Evidence: but are not in the form Evidence: <ID> "quote" [A#] (single quotes, **Evidence:**, a
    missing tag). Before Oct 23 these only showed up as scored evidence left out of the report (finding 14)."""
    out = []
    for m in EVIDENCE_MENTION.finditer(report):
        line = m.group(0).strip()
        if not REPORT_EVIDENCE.search(line):
            out.append(line[:100])
    return out


def evidence_check(evidence_md: str, report: str) -> str:
    lines = parse_bundle(evidence_md)
    citations = list(REPORT_EVIDENCE.finditer(report))
    problems, verified = [], 0
    for m in citations:
        eid, digit, quoted, tag = m.groups()
        issues = []
        if eid not in lines:
            issues.append("ID is not in the bundle")
        else:
            if tag != f"A{digit}":
                issues.append(f"tag [{tag}] does not match the ID's family [A{digit}]")
            quoted = (quoted or "").strip()
            if not quoted:
                issues.append("no quote; a citation proves nothing without the words it cites")
            elif len(quoted) < MIN_QUOTE_CHARS:
                issues.append(f"quote too short to verify ({len(quoted)} characters; at least {MIN_QUOTE_CHARS})")
            elif quoted not in lines[eid]["text"]:
                issues.append("quote does not appear verbatim in that evidence line")
        if issues:
            problems.append(f"{eid} [{tag}]: " + "; ".join(issues) + ".")
        else:
            verified += 1

    for line in code_lines(evidence_md):
        if line not in report:
            problems.append(f"Code line not copied verbatim: {line[:90]}...")
    for fam, body in _findings_without_evidence(report):
        problems.append(f'Finding under [{fam}] has no Evidence: line: "{body}"')
    for line in unparsable_citations(report):
        problems.append(f'Unparsable citation (expected Evidence: <ID> "quote" [A1-A3]): {line}')

    scored = [i for i, info in lines.items() if info["scored"]]
    cited = {m.group(1) for m in citations}
    stray = sorted({f"E{a}.{b}" for a, b in CITATION.findall(report)} - cited - set(lines), key=_id_key)
    if stray:
        problems.append(f"The report names IDs that are not in the bundle: {', '.join(stray)}.")
    left_out = [i for i in scored if i not in cited]
    if left_out:
        problems.append("Scored evidence left out of the report: "
                        + ", ".join(f"{i} ({lines[i]['weight']})" for i in left_out) + ".")
    problems += [f"The report's contradictions: {p}" for p in contradiction_problems(report, lines)]
    written = code_contradictions(evidence_md)
    if written is not None:
        # Since Oct 23 code writes the section and the Reporter copies it, like the code-score lines.
        got = _contradiction_lines(report)
        for line in written:
            if not any(_same_text(line, g) for g in got):
                problems.append(f"Contradictions line not copied from the code: {line[:90]}")
        for g in got:
            if not any(_same_text(line, g) for line in written):
                problems.append(f"The report's Contradictions section has a line the code did not write: {g[:90]}")
    foreign = foreign_identifiers(evidence_md, report)
    if foreign:
        problems.append(f"The report names {', '.join(foreign)}, which this case's evidence does not contain.")
    if candidate_questions(report):
        problems.append("The report has a questions section. Chimera's output goes only to the hiring team and never "
                        "addresses the candidate.")
    out = [
        "EVIDENCE CHECK (code)",
        "",
        f"- Evidence citations in report: {len(citations)}; verified: {verified}",
        f"- Scored evidence lines cited: {len([i for i in scored if i in cited])} of {len(scored)}",
        "",
        "EVIDENCE PROBLEMS",
    ]
    out += [f"- {p}" for p in problems] or ["- none"]
    out += ["", "Note: this proves quotes are real and correctly tagged. It does not prove the sentences are right."]
    return "\n".join(out)
