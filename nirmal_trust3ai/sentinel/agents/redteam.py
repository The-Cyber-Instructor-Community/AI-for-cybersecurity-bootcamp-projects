"""Agent 3 - Red-Team. Runs ONLY the attacks the threat model and static scan point to.

This is the token-saving core of the design: instead of firing every probe, select()
keeps a corpus attack only when its check family matches a possible threat or a static
finding. Plus three baseline probes that always run, so a flaw both earlier agents
missed still gets one shot.

Each kept attack is run once in the sandbox (local or docker); an oracle (plain code,
no LLM) decides success. No automated prompt mutation - these are fixed, labelled probes
against a local mock app.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from sentinel.harness import oracles, sandbox
from sentinel.kb import loader
from sentinel.models import Attack, AttackResult, Finding, Threat

CORPUS = Path(__file__).resolve().parent.parent / "attacks" / "corpus.yaml"


def load_corpus() -> list[tuple[Attack, bool]]:
    """Return [(attack, is_baseline), ...] from the corpus file."""
    raw = yaml.safe_load(CORPUS.read_text())["attacks"]
    out = []
    for a in raw:
        baseline = a.pop("baseline", False)
        out.append((Attack(**a), baseline))
    return out


def select(threats: list[Threat], findings: list[Finding],
           corpus: list[tuple[Attack, bool]] | None = None) -> list[Attack]:
    """Keep attacks whose family matches a possible threat or a static finding; always keep baselines.

    A matched attack is tagged with the OWASP/ATLAS of its family and a `target` note saying
    why it was chosen. This is the only step that decides what the Red-Team spends tokens on.
    """
    corpus = corpus or load_corpus()
    fams = loader.families()
    possible = {t.check_family for t in threats if t.likelihood != "unlikely"}
    flagged = {f.check_family for f in findings}
    plan: list[Attack] = []
    for attack, baseline in corpus:
        fam = attack.check_family
        reason = None
        if baseline:
            reason = "baseline"
        elif fam in possible and fam in flagged:
            reason = f"threat + static finding (family {fam})"
        elif fam in possible:
            reason = f"threat only (family {fam})"
        elif fam in flagged:
            reason = f"static finding only (family {fam})"
        if reason:
            plan.append(attack.model_copy(update={
                "owasp": fams[fam]["owasp"], "atlas": fams[fam]["atlas"], "target": reason}))
    # De-duplicate baseline vs matched on id, keeping the first (matched) copy.
    seen, unique = set(), []
    for a in plan:
        if a.id not in seen:
            seen.add(a.id)
            unique.append(a)
    return unique


def run_attack(attack: Attack, backend: str = "local", llm_backend: str = "fake",
               target_dir=sandbox.TARGET) -> AttackResult:
    docs = {attack.doc_name: attack.payload} if attack.channel == "document" else None
    message = attack.payload if attack.channel == "user_message" else "My printer is not working, any tips?"
    result = sandbox.run_case(message, docs=docs, backend=backend, llm_backend=llm_backend, target_dir=target_dir)
    success, reason = oracles.check(attack, result)
    transcript = (f"reply: {result.get('reply', '')}\n"
                  f"tool_log: {result.get('tool_log')}\noutbox: {result.get('outbox')}")
    return AttackResult(attack_id=attack.id, check_family=attack.check_family, owasp=attack.owasp,
                        atlas=attack.atlas, success=success, reason=reason, transcript=transcript,
                        tokens_used=result.get("tokens", 0))


def run_plan(plan: list[Attack], backend: str = "local", llm_backend: str = "fake",
             target_dir=sandbox.TARGET) -> list[AttackResult]:
    return [run_attack(a, backend, llm_backend, target_dir) for a in plan]
