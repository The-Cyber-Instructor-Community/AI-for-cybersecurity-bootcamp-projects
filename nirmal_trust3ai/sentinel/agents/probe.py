"""Behavioral probing - run probes whose outcome needs judgement, not a canary.

Static analysis finds code weaknesses; some risks (LLM02 sensitive-info disclosure, behavioral
excessive agency) only show in what the app SAYS. These probes run through the same sandbox and
are judged by the llm_judge oracle. Needs a target with a run_case entry point and SENTINEL_LLM.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from sentinel.harness import http_adapter, sandbox
from sentinel.kb import loader
from sentinel.models import Attack, AttackResult

PROBES = Path(__file__).resolve().parent.parent / "attacks" / "behavioral.yaml"


def load_probes() -> list[Attack]:
    fams = loader.families()
    out = []
    for p in yaml.safe_load(PROBES.read_text())["probes"]:
        fam = p["check_family"]
        out.append(Attack(owasp=fams[fam]["owasp"], atlas=fams[fam]["atlas"], **p))
    return out


def run_probes(target_dir=sandbox.TARGET, backend: str = "local", llm_backend: str = "fake",
               http_config: "http_adapter.HttpConfig | None" = None) -> list[AttackResult]:
    """Run behavioral probes. If http_config is given, probe a RUNNING app over HTTP instead of run_case."""
    from sentinel.harness import oracles
    results = []
    for probe in load_probes():
        if http_config is not None:
            result = http_adapter.run_case_http(probe.payload, http_config)
        else:
            result = sandbox.run_case(probe.payload, backend=backend, llm_backend=llm_backend, target_dir=target_dir)
        bad, reason = oracles.check(probe, result)
        results.append(AttackResult(
            attack_id=probe.id, check_family=probe.check_family, owasp=probe.owasp, atlas=probe.atlas,
            success=bad, reason=reason, transcript=f"reply: {result.get('reply','')}", tokens_used=result.get("tokens", 0)))
    return results
