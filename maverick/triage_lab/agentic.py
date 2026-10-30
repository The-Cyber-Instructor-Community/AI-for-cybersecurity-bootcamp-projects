"""Agentic investigation: the AI gathers its own evidence with read-only tools.

Instead of receiving a ready-made evidence bundle, the agent starts with only the
alerts and the alerted events, then decides what to look at:

  search_events    events for a user / host / source around the incident
  get_event        one event in full
  process_tree     process creations on a host around the incident
  log_health       is a log source healthy in the incident window?
  lookup_user      the identity record (role, privileged)
  search_knowledge RAG notes (only when RAG is on)
  lookup_asset     owner, criticality and crown-jewel status of a host or bucket
  user_baseline    has this user done the same thing in the 7 days before?

Guard-rails (all in code, not up to the model):
  * tools are read-only and limited to the incident's time neighbourhood
  * at most `max_tool_calls` calls, then the agent must answer
  * if it still gives no valid verdict, it falls back to the code-built bundle
  * the verifier and gates still decide; they check claims against exactly the
    events the agent actually retrieved
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta

from .agent import Agent, parse_json, stub_verdict, system_prompt
from .config import settings
from .correlate import Incident
from .detections import Alert
from .log_quality import LogQuality
from .rag import Retriever
from .schema import Event

INVESTIGATION_RULES = """

INVESTIGATION
You start with only the alerts and the events that fired them. Use the tools to gather the evidence an
experienced analyst would check (related activity by the same user or host, process ancestry, whether the
log sources were healthy, who the user is) before deciding. You may make at most {max_calls} tool calls.
Only events returned by tools (or shown below) may be cited. When you have enough evidence, reply with
the final JSON object and nothing else."""

TOOLS = [
    {"type": "function", "function": {
        "name": "search_events",
        "description": "Find events around the incident. Filter by user, host, source (email|identity|endpoint|cloud) "
                       "and event_type. Returns at most `limit` events, oldest first.",
        "parameters": {"type": "object", "properties": {
            "user": {"type": "string"}, "host": {"type": "string"}, "source": {"type": "string"},
            "event_type": {"type": "string"},
            "minutes_before": {"type": "integer", "description": "minutes before the incident start (max 180)"},
            "minutes_after": {"type": "integer", "description": "minutes after the incident end (max 180)"},
            "limit": {"type": "integer", "description": "max events (max 25)"}}}}},
    {"type": "function", "function": {
        "name": "get_event", "description": "Return one event in full by its ID.",
        "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]}}},
    {"type": "function", "function": {
        "name": "process_tree",
        "description": "Process creation events on a host within N minutes of the incident, with parent processes.",
        "parameters": {"type": "object", "properties": {"host": {"type": "string"},
                                                        "minutes": {"type": "integer"}}, "required": ["host"]}}},
    {"type": "function", "function": {
        "name": "log_health",
        "description": "Health score 0-1 of a log source during the incident window. Low means logs may be missing.",
        "parameters": {"type": "object", "properties": {"source": {"type": "string"}}, "required": ["source"]}}},
    {"type": "function", "function": {
        "name": "lookup_user", "description": "Identity record for a user: role, department, privileged.",
        "parameters": {"type": "object", "properties": {"user": {"type": "string"}}, "required": ["user"]}}},
    {"type": "function", "function": {
        "name": "lookup_asset", "description": "Owner, criticality and crown-jewel status of a host or cloud bucket.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "user_baseline",
        "description": "What is normal for this user: activity in the 7 days before the incident, and whether each "
                       "alerted behaviour (country/device, bucket/client, process/parent, link domain) was seen before.",
        "parameters": {"type": "object", "properties": {"user": {"type": "string"}}, "required": ["user"]}}},
    {"type": "function", "function": {
        "name": "search_knowledge", "description": "Search triage notes about ATT&CK techniques.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]


class Toolbox:
    def __init__(self, inc: Incident, events: list[Event], events_by_id: dict, lq: LogQuality,
                 users: dict, retriever: Retriever | None, with_context: bool, gate_ctx: dict | None = None):
        self.inc, self.events, self.by_id, self.lq = inc, events, events_by_id, lq
        self.users, self.retriever, self.with_context = users, retriever, with_context
        self.start = datetime.fromisoformat(inc.start)
        self.end = datetime.fromisoformat(inc.end)
        self.seen: dict[str, dict] = {}          # every event the agent has been shown
        self.knowledge: list[dict] = []
        self.used_context = False
        self.gate_ctx = gate_ctx or {"assets": {}, "baseline": None}
        self.assets: dict = {}
        self.baseline: dict | None = None

    def available(self) -> list[dict]:
        names = {"search_events", "get_event", "process_tree", "log_health", "lookup_asset", "user_baseline"}
        if self.with_context:
            names.add("lookup_user")
        if self.retriever:
            names.add("search_knowledge")
        return [t for t in TOOLS if t["function"]["name"] in names]

    def _show(self, evs: list[Event]) -> list[dict]:
        out = [e.compact() for e in evs]
        for c in out:
            self.seen[c["id"]] = c
        return out

    def _window(self, before: int = 60, after: int = 60):
        before, after = max(0, min(int(before), 180)), max(0, min(int(after), 180))
        return self.start - timedelta(minutes=before), self.end + timedelta(minutes=after)

    def call(self, name: str, args: dict) -> dict:
        args = args or {}
        if name not in {t["function"]["name"] for t in self.available()}:
            return {"error": f"unknown or unavailable tool '{name}'"}
        try:
            if name == "search_events":
                lo, hi = self._window(args.get("minutes_before", 60), args.get("minutes_after", 60))
                hits = [e for e in self.events if lo <= e.time <= hi
                        and (not args.get("user") or e.user == args["user"])
                        and (not args.get("host") or e.host == args["host"])
                        and (not args.get("source") or e.source == args["source"])
                        and (not args.get("event_type") or e.event_type == args["event_type"])]
                limit = max(1, min(int(args.get("limit", 15)), 25))
                return {"count": len(hits), "events": self._show(hits[:limit])}
            if name == "get_event":
                e = self.by_id.get(str(args.get("event_id")))
                if not e or abs((e.time - self.start).total_seconds()) > 86400:
                    return {"error": "event not found near this incident"}
                return {"event": self._show([e])[0]}
            if name == "process_tree":
                lo, hi = self._window(args.get("minutes", 60), args.get("minutes", 60))
                hits = [e for e in self.events if lo <= e.time <= hi and e.host == args.get("host")
                        and e.event_type == "process_create"]
                return {"count": len(hits), "events": self._show(hits[:25])}
            if name == "log_health":
                lo, hi = self._window(30, 30)
                return {"source": args.get("source"), "score": self.lq.window_score(str(args.get("source")), lo, hi)}
            if name == "lookup_user":
                self.used_context = True
                rec = self.users.get(str(args.get("user")))
                return {"user": args.get("user"), "record": {k: v for k, v in rec.items() if k != "user"} if rec else None}
            if name == "lookup_asset":
                from .context import load_assets
                rec = load_assets().get(str(args.get("name")))
                if rec:
                    self.assets[rec["asset"]] = {k: v for k, v in rec.items() if k != "asset"}
                return {"asset": args.get("name"), "record": self.assets.get(str(args.get("name")))}
            if name == "user_baseline":
                if str(args.get("user")) != self.inc.user:
                    return {"error": "baseline is only available for the incident's user"}
                self.baseline = self.gate_ctx["baseline"]
                return self.baseline
            if name == "search_knowledge":
                chunks = self.retriever.search(str(args.get("query", "")), settings()["agent"]["rag_top_k"])
                found = [{"doc": c.doc, "section": c.heading, "text": c.text} for c in chunks]
                self.knowledge.extend(k for k in found if k not in self.knowledge)
                return {"notes": found}
        except (TypeError, ValueError) as exc:
            return {"error": f"bad arguments: {exc}"}
        return {"error": "unhandled"}


def _text_tool_call(content: str):
    """Some models write a tool call as JSON text instead of a native tool call."""
    m = re.search(r"\{.*\}", content or "", flags=re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    name = d.get("tool") or d.get("name")
    if isinstance(name, str) and "decision" not in d:
        return [{"function": {"name": name, "arguments": d.get("arguments") or d.get("parameters") or {}}}]
    return None


def investigate(agent: Agent, inc: Incident, alerts_by_id: dict[str, Alert], events: list[Event],
                events_by_id: dict, lq: LogQuality, users: dict, retriever: Retriever | None,
                with_context: bool, fallback_bundle, baseline=None) -> dict:
    """Run the bounded tool loop. Returns verdict, the evidence bundle the verifier
    should use, the trajectory and bookkeeping."""
    max_calls = settings()["agent"].get("max_tool_calls", 6)
    from .evidence import gate_context
    gate_ctx = gate_context(inc, [events_by_id[e] for e in inc.event_ids if e in events_by_id], events, baseline)
    box = Toolbox(inc, events, events_by_id, lq, users, retriever, with_context, gate_ctx)
    alerts = [alerts_by_id[a] for a in inc.alert_ids]
    alerted = box._show([events_by_id[e] for e in inc.event_ids if e in events_by_id])
    hosts = sorted({e["host"] for e in alerted if e.get("host")})
    opening = (f"<incident user=\"{inc.user}\" hosts=\"{', '.join(hosts)}\" "
               f"window=\"{inc.start} to {inc.end}\"/>\n<alerts>\n"
               + json.dumps([{"rule": a.rule_id, "title": a.title, "level": a.level, "techniques": a.techniques,
                              "event_ids": a.event_ids} for a in alerts], indent=1)
               + "\n</alerts>\n<events>\n" + "\n".join(json.dumps(e) for e in alerted) + "\n</events>")
    rules = system_prompt(agent.playbook) + INVESTIGATION_RULES
    messages = [{"role": "system", "content": rules.replace("{max_calls}", str(max_calls))},
                {"role": "user", "content": opening}]
    trajectory, invalid, raw, verdict, t0 = [], 0, "", None, time.time()

    if agent.backend == "stub":                      # scripted, deterministic: wiring and tests only
        script = [("search_events", {"user": inc.user, "minutes_before": 30, "minutes_after": 30}),
                  ("log_health", {"source": "endpoint"}), ("log_health", {"source": "cloud"}),
                  ("user_baseline", {"user": inc.user})]
        if with_context:
            script.append(("lookup_user", {"user": inc.user}))
        for name, args in script:
            res = box.call(name, args)
            trajectory.append({"tool": name, "args": args, "error": res.get("error")})
        verdict = stub_verdict(_bundle(box, inc, alerts, lq, users if box.used_context else {}))
        raw = json.dumps(verdict)
    else:
        try:
            calls_made = 0
            while True:
                msg = agent.chat_tools(messages, box.available())
                calls = msg.get("tool_calls") or _text_tool_call(msg.get("content", ""))
                if calls and calls_made < max_calls:
                    messages.append(msg)
                    for c in calls[: max_calls - calls_made]:
                        fn = c.get("function", {})
                        name, args = fn.get("name"), fn.get("arguments") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        res = box.call(name, args)
                        invalid += "error" in res
                        trajectory.append({"tool": name, "args": args, "error": res.get("error")})
                        messages.append({"role": "tool", "tool_name": name, "content": json.dumps(res)[:12000]})
                        calls_made += 1
                    continue
                raw = msg.get("content", "")
                verdict = parse_json(raw)
                if verdict is None:              # ask once more, forcing JSON
                    messages += [msg, {"role": "user", "content":
                                       "Stop investigating. Return the final JSON verdict now."}]
                    raw = agent._cached_message(messages, json_mode=True)["content"]
                    verdict = parse_json(raw)
                break
        except FileNotFoundError:
            raise
        except Exception as exc:                 # model error mid-loop -> fall back below
            raw = f"MODEL ERROR: {exc}"

    fallback = verdict is None
    if fallback:                                 # safety net: the code-built evidence bundle
        bundle = fallback_bundle()
        verdict, raw, _ = agent.triage(bundle)
    else:
        bundle = _bundle(box, inc, alerts, lq, users if box.used_context else {})
    return {"verdict": verdict, "raw": raw, "bundle": bundle, "trajectory": trajectory,
            "invalid_tool_calls": invalid, "fallback": fallback, "seconds": round(time.time() - t0, 2),
            "off_target_calls": sum(1 for s in trajectory if s["args"].get("user") not in (None, "", inc.user))}


def _bundle(box: Toolbox, inc: Incident, alerts: list[Alert], lq: LogQuality, users: dict) -> dict:
    """What the agent saw, in the same shape as a code-built bundle (for verifier and gates)."""
    pad = timedelta(minutes=settings()["pipeline"]["context_padding_minutes"])
    lo, hi = box.start - pad, box.end + pad
    ctx = users.get(inc.user)
    return {
        "incident_id": inc.id, "user": inc.user, "risk": inc.risk,
        "window": {"start": lo.isoformat(), "end": hi.isoformat()},
        "alerts": [{"alert_id": a.id, "rule": a.rule_id, "title": a.title, "level": a.level,
                    "techniques": a.techniques, "event_ids": a.event_ids} for a in alerts],
        "events": sorted(box.seen.values(), key=lambda e: e["ts"]),
        "log_health": lq.window_scores(lo, hi),      # gates always use the code's own health check
        "user_context": {k: v for k, v in ctx.items() if k != "user"} if ctx else None,
        "knowledge": box.knowledge, "mode": "agentic",
        "assets": box.assets or None, "baseline": box.baseline,     # only what the agent looked up
        "gate_context": box.gate_ctx,
    }
