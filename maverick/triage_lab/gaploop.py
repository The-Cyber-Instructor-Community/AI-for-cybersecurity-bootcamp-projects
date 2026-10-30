"""Self-correction loop for DETECTIONS: draft a rule for a missed technique, then test it.

1. Find malicious events that no signature rule caught (from the answer key).
2. Draft a Sigma rule for them:
     backend=ollama  the model writes the YAML from examples of missed and benign events,
                     sees its own backtest numbers and revises, up to 3 attempts
     backend=stub    simple rule induction (NOT AI): keep the fields that are identical
                     across the missed events and use the smallest number as a threshold
3. Backtest the draft on ALL events: recall on that technique, false positives on
   benign activity. Accept only if recall >= min_recall and FPs <= max_false_positives.
4. Accepted or not, the draft is written to rules/drafts/ for a HUMAN to approve.
   Nothing is promoted to rules/sigma automatically.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

import yaml

from .agent import Agent
from .config import path, settings
from .detections import Rule, load_rules
from .schema import Event, load_events, read_jsonl

PROMPT = """You write Sigma detection rules. Write ONE rule that matches the MISSED malicious events below but none of the BENIGN events.
Use only these field names: {fields}. Allowed modifiers: contains, startswith, endswith, all, gte, gt, lte, lt.
Reply with only the YAML, in this exact layout:
title: ...
tags: [attack.{technique_tag}]
detection:
  selection:
    field: value
  condition: selection
level: medium

MISSED malicious events ({technique}):
{missed}

BENIGN events of the same type:
{benign}"""


def missed_events(events: list[Event]) -> dict[str, list[Event]]:
    by_id = {e.id: e for e in events}
    labels = list(read_jsonl(path("data_dir") / "labels.jsonl"))
    rules = load_rules()
    out = defaultdict(list)
    for l in labels:
        if l["malicious"] and l["observed"] and l["technique"] and l["event_id"] in by_id:
            ev = by_id[l["event_id"]]
            if not any(r.matches(ev) and l["technique"] in r.techniques for r in rules):
                out[l["technique"]].append(ev)
    return out


def induce_rule(technique: str, missed: list[Event]) -> dict:
    """Stub drafting: constant fields become selections, numbers become >= thresholds."""
    sel = {"event_type": missed[0].event_type}
    keys = set.intersection(*(set(e.fields) for e in missed))
    for k in sorted(keys):
        vals = [e.fields[k] for e in missed]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            sel[f"{k}|gte"] = min(vals)
        elif len({json.dumps(v) for v in vals}) == 1 and not str(vals[0]).startswith("DEV-"):
            sel[k] = vals[0]
    return {"title": f"Draft rule for missed {technique}", "tags": [f"attack.{technique.lower()}"],
            "detection": {"selection": sel, "condition": "selection"}, "level": "medium"}


def _yaml(raw: str) -> dict:
    text = re.sub(r"^```(?:yaml)?|```$", "", raw.strip(), flags=re.M)
    d = yaml.safe_load(text)
    if not isinstance(d, dict) or "detection" not in d:
        raise ValueError("model did not return a rule with a 'detection' block")
    return d


def llm_rule(agent: Agent, technique: str, missed: list[Event], benign: list[Event],
             events: list[Event], attempts: int = 3) -> tuple[dict, dict, list[dict]]:
    """Agentic drafting: draft -> backtest -> feed the numbers back -> revise (up to `attempts`)."""
    cfg = settings()["gap_loop"]
    fields = sorted({"event_type", "user"} | {k for e in missed + benign for k in e.fields})
    msg = PROMPT.format(fields=", ".join(fields), technique=technique, technique_tag=technique.lower(),
                        missed="\n".join(json.dumps(e.compact()) for e in missed[:5]),
                        benign="\n".join(json.dumps(e.compact()) for e in benign[:5]))
    messages, history = [{"role": "user", "content": msg}], []
    draft, bt = None, None
    for i in range(attempts):
        raw = agent.chat(messages)
        try:
            draft = _yaml(raw)
            bt = backtest(draft, technique, events)
        except Exception as exc:  # noqa: BLE001 - feed any problem back to the model
            bt = {"error": str(exc), "recall": 0.0, "false_positives": None, "matches": 0}
        history.append({"attempt": i + 1, **{k: bt.get(k) for k in ("recall", "false_positives", "error")}})
        if "error" not in bt and bt["recall"] >= cfg["min_recall"] and bt["false_positives"] <= cfg["max_false_positives"]:
            break
        feedback = (f"Backtest of your rule: {bt.get('error') or ''} recall {bt['recall']} "
                    f"(need >= {cfg['min_recall']}), false positives {bt.get('false_positives')} "
                    f"(need <= {cfg['max_false_positives']}). Revise the rule. Reply with only the YAML.")
        messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": feedback}]
    if draft is None:
        raise ValueError("no usable rule after all attempts")
    return draft, bt, history


def backtest(rule_yaml: dict, technique: str, events: list[Event]) -> dict:
    rule = Rule.from_dict(rule_yaml, "DRAFT")
    labels = {l["event_id"]: l for l in read_jsonl(path("data_dir") / "labels.jsonl") if l["event_id"]}
    hits = [e for e in events if rule.matches(e)]
    target = [l for l in labels.values() if l["malicious"] and l["technique"] == technique]
    tp = sum(1 for e in hits if labels.get(e.id, {}).get("technique") == technique)
    fp = sum(1 for e in hits if not labels.get(e.id, {}).get("malicious"))
    return {"matches": len(hits), "recall": round(tp / len(target), 3) if target else 0.0,
            "false_positives": fp}


def run(backend: str | None = None) -> list[dict]:
    cfg = settings()["gap_loop"]
    events, _ = load_events(path("data_dir") / "events.jsonl")
    agent = Agent(backend)
    results = []
    for technique, missed in sorted(missed_events(events).items(), key=lambda kv: -len(kv[1])):
        benign = [e for e in events if e.event_type == missed[0].event_type][:200]
        labels = {l["event_id"]: l for l in read_jsonl(path("data_dir") / "labels.jsonl") if l["event_id"]}
        benign = [e for e in benign if not labels.get(e.id, {}).get("malicious")]
        try:
            if agent.backend == "stub":
                draft, attempts = induce_rule(technique, missed), [{"attempt": 1}]
                bt = backtest(draft, technique, events)
            else:
                draft, bt, attempts = llm_rule(agent, technique, missed, benign, events)
        except FileNotFoundError:
            raise
        except Exception as exc:  # a malformed model answer is a result, not a crash
            results.append({"technique": technique, "missed": len(missed), "accepted": False,
                            "error": str(exc)})
            continue
        accepted = bt["recall"] >= cfg["min_recall"] and bt["false_positives"] <= cfg["max_false_positives"]
        draft["status"] = "experimental"
        draft["description"] = (f"Drafted by gap loop ({agent.label}) for {len(missed)} missed {technique} events. "
                                f"Backtest recall {bt['recall']}, false positives {bt['false_positives']}. "
                                f"{'Passed' if accepted else 'FAILED'} the backtest gate. Needs human approval.")
        name = f"draft_{technique.replace('.', '_').lower()}_{'pass' if accepted else 'fail'}.yml"
        (path("drafts_dir") / name).write_text(yaml.safe_dump(draft, sort_keys=False), encoding="utf-8")
        results.append({"technique": technique, "missed": len(missed), "draft": name,
                        "selection": draft["detection"].get("selection"), **bt, "accepted": accepted,
                        "attempts": attempts})
    (path("results_dir") / "gap_loop.json").write_text(json.dumps(results, indent=2, default=str))
    return results
