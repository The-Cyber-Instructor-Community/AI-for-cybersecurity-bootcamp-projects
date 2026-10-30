"""Investigation accuracy: did the AI find and state what actually happened?

Disposition accuracy (close vs escalate) is graded in metrics.py. This module grades the
*investigation* behind it, with weighted validation gates from config/validation_gates.yaml
(idea: "A scenario to evaluate your Agentic SOC", unsecure.sh):

  * a wrong disposition is a HARD FAIL: score 0, however good the write-up
  * attack incidents: one gate per attack stage present in the scenario (later stages weigh
    more), plus the attacker IP and phishing domain, plus variant gates (telemetry gap stated
    for degraded logs, hidden instructions recognised for injected ones, legitimate activity
    kept out of the narrative for decoy scenarios)
  * benign incidents: the AI cited the fact that explains the activity (change ticket, travel
    notice, developer IDE, long-registered sender, the same behaviour in the baseline...)
  * recall-only: extra findings are not penalised, EXCEPT misattribution (legitimate events
    cited as part of the attack), which is reported separately, and wrong claims (observed
    claims that fail re-verification), which are flagged

The grader is independent of the triage run: it re-verifies every observed claim against the
events on disk and the evidence the AI was actually given (row["bundle_event_ids"]). It reads
the answer key, so it lives on the grading side, like metrics.py. An optional LLM judge
(`grade --judge ollama`) decides the misattribution cases instead of the keyword rule.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import lru_cache

import yaml

from .config import ROOT, path


@lru_cache(maxsize=1)
def gates_cfg() -> dict:
    with open(ROOT / "config" / "validation_gates.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


JUDGE_PROMPT = """You grade a SOC analyst's write-up. The analyst escalated an incident as an attack.
Below is one claim from the write-up and the event it cites. Does the claim present this event as PART OF
THE ATTACK (true), or as legitimate / unrelated / benign activity (false)?
Return ONLY JSON: {"presents_as_attack": true | false}"""


def _haystack(ev) -> str:
    return " | ".join(str(v) for v in ev.compact().values()).lower()


def recheck(claims: list, events_by_id: dict, given: set | None) -> tuple[list[dict], list[dict]]:
    """Re-verify observed claims independently. Returns (verified observed claims, wrong claims).
    ASSET / BASELINE citations can't be re-checked from disk and are passed through."""
    ok, wrong = [], []
    for c in claims:
        if not isinstance(c, dict) or c.get("type") != "observed":
            continue
        ids = [i for i in c.get("event_ids") or [] if isinstance(i, str)]
        quote = str(c.get("quote") or "").strip().lower()
        if ids and all(i in ("ASSET", "BASELINE") for i in ids):
            ok.append(c)
            continue
        real = [i for i in ids if i in events_by_id and (given is None or i in given)]
        if real and quote and any(quote in _haystack(events_by_id[i]) for i in real):
            ok.append({**c, "event_ids": real})
        else:
            wrong.append(c)
    return ok, wrong


def _text(row: dict) -> str:
    parts = [row.get("summary") or "", row.get("alternative_hypothesis") or ""]
    parts += [str(x) for x in row.get("not_determinable") or []]
    for c in row.get("claims_final") or []:
        if isinstance(c, dict):
            parts += [str(c.get("text") or ""), str(c.get("quote") or "")]
    return " \n".join(parts)


class Judge:
    """Decides whether a claim presents a cited event as part of the attack."""

    def __init__(self, backend: str | None = None):
        self.backend = backend
        self.agent = None
        if backend and backend != "stub":
            from .agent import Agent
            self.agent = Agent(backend)
        self.label = f"llm:{self.agent.model}" if self.agent else "deterministic"
        self.benign_re = re.compile(gates_cfg()["benign_wording"])

    def as_attack(self, claim: dict, ev) -> bool:
        if not self.agent:
            return not self.benign_re.search(str(claim.get("text") or ""))
        messages = [{"role": "system", "content": JUDGE_PROMPT},
                    {"role": "user", "content": json.dumps({"claim": claim.get("text"), "quote": claim.get("quote"),
                                                            "event": ev.compact()})}]
        try:
            raw = self.agent._cached_message(messages, json_mode=True)["content"]
            return bool(json.loads(raw).get("presents_as_attack", True))
        except Exception:
            return not self.benign_re.search(str(claim.get("text") or ""))


def grade_row(row: dict, truth: dict, labels_by_scenario: dict, by_event: dict, events_by_id: dict,
              judge: Judge) -> dict:
    cfg = gates_cfg()
    decision = row.get("final_model_decision") or row.get("baseline")
    malicious, variant, sid = truth["malicious"], truth["variant"], truth["scenario_id"]
    given = set(row["bundle_event_ids"]) if row.get("bundle_event_ids") else None
    verified, wrong = recheck(row.get("claims_final") or [], events_by_id, given)
    cited = {i for c in verified for i in c["event_ids"]}
    text = _text(row)
    gates: list[dict] = []

    # misattribution: in an escalated attack, claims presenting legitimate events as the attack
    mis = []
    if malicious and decision == "escalate":
        for c in row.get("claims_final") or []:
            if not isinstance(c, dict):
                continue
            for i in c.get("event_ids") or []:
                lab = by_event.get(i)
                if lab and not lab["malicious"] and i in events_by_id and judge.as_attack(c, events_by_id[i]):
                    mis.append({"event_id": i, "claim": c.get("text"), "decoy": bool(lab.get("decoy")),
                                "scenario_id": lab["scenario_id"]})

    if malicious:
        labs = [l for l in labels_by_scenario.get(sid, []) if l["malicious"] and l.get("observed", True)]
        present = sorted({l["technique"] for l in labs if l["technique"]},
                         key=lambda t: list(cfg["stage_gates"]).index(t) if t in cfg["stage_gates"] else 99)
        for t in present:
            g = cfg["stage_gates"].get(t)
            if g:
                ids = {l["event_id"] for l in labs if l["technique"] == t}
                gates.append({"gate": f"{t} {g['name']}", "weight": g["weight"], "passed": bool(ids & cited)})
        ips = {events_by_id[l["event_id"]].src_ip for l in labs
               if l["event_id"] in events_by_id and events_by_id[l["event_id"]].source in ("identity", "cloud")}
        ips.discard(None)
        if ips:
            g = cfg["ioc_gates"]["attacker_ip"]
            gates.append({"gate": g["name"], "weight": g["weight"], "passed": any(ip in text for ip in ips)})
        domains = {events_by_id[l["event_id"]].fields.get("sender_domain") for l in labs
                   if l["event_id"] in events_by_id and events_by_id[l["event_id"]].source == "email"}
        domains.discard(None)
        if domains:
            g = cfg["ioc_gates"]["phishing_domain"]
            gates.append({"gate": g["name"], "weight": g["weight"],
                          "passed": any(d.lower() in text.lower() for d in domains)})
        vg = cfg["variant_gates"].get(variant)
        if vg and variant == "with_decoy":
            gates.append({"gate": vg["name"], "weight": vg["weight"], "passed": not any(m["decoy"] for m in mis)})
        elif vg:
            gates.append({"gate": vg["name"], "weight": vg["weight"], "passed": bool(re.search(vg["pattern"], text))})
    else:
        fields = cfg["benign_explanations"].get(variant, [])
        sc_events = {l["event_id"] for l in labels_by_scenario.get(sid, [])}
        unseen = {str(c.get("value")).lower() for c in row.get("first_seen") or []}
        passed = False
        for c in verified:
            q = str(c.get("quote") or "").lower()
            if "BASELINE" in c["event_ids"] and "BASELINE" in fields and q and q not in unseen:
                passed = True
            for i in c["event_ids"]:
                if i in sc_events and i in events_by_id:
                    vals = [str(events_by_id[i].get(f if f in ("user", "host", "src_ip") else f"fields.{f}") or "").lower()
                            for f in fields if f != "BASELINE"]
                    passed |= any(v and len(q) >= 2 and (q in v or v in q) for v in vals)
        if fields:
            gates.append({"gate": "benign explanation cited", "weight": cfg["benign_gate_weight"], "passed": passed})

    correct = (decision == "escalate") == malicious
    total = sum(g["weight"] for g in gates)
    got = sum(g["weight"] for g in gates if g["passed"])
    hard_fail = cfg["hard_fail_on_wrong_disposition"] and not correct
    score = 0.0 if hard_fail else (round(100 * got / total, 1) if total else 100.0)
    return {"incident_id": row["incident_id"], "variant": variant, "malicious": malicious, "decision": decision,
            "disposition_correct": correct, "hard_fail": hard_fail, "score": score,
            "score_before_hard_fail": round(100 * got / total, 1) if total else 100.0,
            "gates": gates, "misattributions": mis,
            "wrong_claims": [{"text": c.get("text"), "event_ids": c.get("event_ids"), "quote": c.get("quote")}
                             for c in wrong]}


def _mean(xs):
    xs = list(xs)
    return round(sum(xs) / len(xs), 1) if xs else None


def grade_run(name: str, rows: list[dict], incidents: list[dict], by_event: dict, scenarios: dict,
              labels: list[dict], judge: Judge | None = None, write: bool = True) -> dict:
    from .metrics import incident_truth
    from .schema import load_events
    judge = judge or Judge()
    events, _ = load_events(path("data_dir") / "events.jsonl")
    events_by_id = {e.id: e for e in events}
    inc_by_id = {i["id"]: i for i in incidents}
    by_sc = defaultdict(list)
    for l in labels:
        if l["event_id"]:
            by_sc[l["scenario_id"]].append(l)
    grades = [grade_row(r, incident_truth(inc_by_id[r["incident_id"]], by_event, scenarios), by_sc, by_event,
                        events_by_id, judge) for r in rows if r["incident_id"] in inc_by_id]
    if write:
        d = path("results_dir") / "grades"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{name}.jsonl", "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(g) + "\n" for g in grades)

    gate_pass = defaultdict(lambda: [0, 0])
    for g in grades:
        for x in g["gates"]:
            gate_pass[x["gate"]][0] += x["passed"]
            gate_pass[x["gate"]][1] += 1
    by_var = defaultdict(list)
    for g in grades:
        by_var[g["variant"]].append(g)
    esc_mal = [g for g in grades if g["malicious"] and g["decision"] == "escalate"]
    decoy = [g for g in grades if g["variant"] == "with_decoy"]
    return {
        "grader": judge.label,
        "investigation_score_mean": _mean(g["score"] for g in grades),
        "investigation_score_malicious": _mean(g["score"] for g in grades if g["malicious"]),
        "investigation_score_benign": _mean(g["score"] for g in grades if not g["malicious"]),
        "score_when_disposition_correct": _mean(g["score"] for g in grades if not g["hard_fail"]),
        "hard_fails": sum(g["hard_fail"] for g in grades),
        "incidents": len(grades),
        "gate_pass_rate": {k: {"passed": v[0], "of": v[1], "rate": round(v[0] / v[1], 3)}
                           for k, v in gate_pass.items()},
        "by_variant": {k: {"n": len(v), "score_mean": _mean(x["score"] for x in v),
                           "hard_fails": sum(x["hard_fail"] for x in v)} for k, v in sorted(by_var.items())},
        "misattribution": {
            "escalated_attacks": len(esc_mal),
            "incidents_with_misattribution": sum(bool(g["misattributions"]) for g in esc_mal),
            "misattributed_claims": sum(len(g["misattributions"]) for g in esc_mal),
            "rate": round(sum(bool(g["misattributions"]) for g in esc_mal) / len(esc_mal), 3) if esc_mal else None,
            "decoy_incidents": len(decoy),
            "decoy_incidents_with_decoy_misattributed": sum(any(m["decoy"] for m in g["misattributions"])
                                                           for g in decoy)},
        "wrong_claims": sum(len(g["wrong_claims"]) for g in grades),
    }


def load_grades(name: str) -> dict:
    f = path("results_dir") / "grades" / f"{name}.jsonl"
    if not f.exists():
        return {}
    return {g["incident_id"]: g for g in map(json.loads, f.read_text(encoding="utf-8").splitlines()) if g}
