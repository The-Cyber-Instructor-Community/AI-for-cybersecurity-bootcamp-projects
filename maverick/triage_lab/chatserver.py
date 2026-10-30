"""A chat front-end for the demo: ask the lab about any incident in plain words.

    python -m triage_lab serve                 # http://localhost:8765  (POST /ask {"message": "..."})

LangFlow's Playground (or any chat UI) sends each message here and shows the reply. The answers
come from the SAVED runs (results/runs/*.jsonl), so they are instant and identical every time, and
every AI answer shown is a real model output. The verifier, gates and answer key stay in this
Python process; the chat window only displays what they decided.

Things you can type (case and wording are forgiving):
  help                              this list
  INC-0006   or   show 6            AI alone vs controls vs the truth, for the main run
  false positive                    the same incident when a colleague asks "is this a false positive?"
  agentic   or   investigate        the same incident when the AI investigated it with tools
  critic                            what the AI critic said
  case file                         the analyst handover file
  list injected | degraded | partial | decoy | attacks | benign | admin | travel | developer
  scoreboard [run]                  headline numbers for a run (default: main)
  red team                          attack success rates (MITRE ATLAS)
  live INC-0006 [false positive]    triage it NOW with the configured model (slow on a laptop)
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import path
from .schema import read_jsonl

LABELS = {"full": "full attack chain", "no_exec": "attack without the PowerShell step",
          "stealthy": "stealthy attack", "partial": "two-stage attack (click + PowerShell)",
          "degraded": "attack during a logging outage", "injected": "attack with a prompt injection",
          "admin_compromise": "compromised admin account", "with_decoy": "attack mixed with the user's real work",
          "newsletter_click": "benign newsletter click", "travel_signin": "benign approved travel sign-in",
          "dev_encoded_ps": "benign developer PowerShell (VS Code)", "admin_enum": "benign ticketed admin task",
          "quarterly_export": "benign ticketed finance export", "backup_job": "benign backup job",
          "new_laptop": "benign new laptop"}
LIST_WORDS = {"injected": ["injected"], "degraded": ["degraded"], "partial": ["partial"], "decoy": ["with_decoy"],
              "admin": ["admin_compromise", "admin_enum"], "travel": ["travel_signin"],
              "developer": ["dev_encoded_ps"], "newsletter": ["newsletter_click"], "finance": ["quarterly_export"],
              "stealthy": ["stealthy"]}


class Lab:
    def __init__(self):
        from .metrics import incident_truth, load_truth
        rd = path("results_dir")
        self.incidents = {i["id"]: i for i in read_jsonl(rd / "pipeline" / "incidents.jsonl")}
        _, by_event, scenarios = load_truth()
        self.truth = {k: incident_truth(v, by_event, scenarios) for k, v in self.incidents.items()}
        self.runs = {f.stem: {r["incident_id"]: r for r in read_jsonl(f)} for f in (rd / "runs").glob("*.jsonl")}
        mf = rd / "metrics.json"
        self.metrics = json.loads(mf.read_text()) if mf.exists() else {}
        self.last = None
        self._live = None

    # ---------------------------------------------------------------- helpers
    def _inc(self, text: str) -> str | None:
        m = re.search(r"inc[-\s_]?0*(\d{1,4})", text, re.I) or re.search(r"\b(?:show|incident|#)\s*0*(\d{1,4})\b", text, re.I)
        if m:
            iid = f"INC-{int(m.group(1)):04d}"
            if iid in self.incidents:
                self.last = iid
                return iid
        return self.last

    def _truth_line(self, iid: str) -> str:
        t = self.truth[iid]
        return f"**Truth (answer key):** {'🔴 REAL ATTACK' if t['malicious'] else '🟢 benign'} · {LABELS.get(t['variant'], t['variant'])}"

    def _first(self, *names):
        return next((n for n in names if n in self.runs), None)

    def _decision(self, r: dict, iid: str, run: str) -> str:
        mal = self.truth[iid]["malicious"]

        def mark(d):
            return "✅" if (d == "escalate") == mal else ("❌ **missed attack**" if mal else "⚠️ extra work")
        lines = [f"### {iid} · {r['user']} · run `{run}`", self._truth_line(iid), "",
                 f"**AI alone → {r['baseline'].upper()}** {mark(r['baseline'])} (confidence {r.get('model_confidence')})",
                 f"> {str(r.get('summary', ''))[:300]}"]
        if "assured_v1" in r and r["assured_v1"] != r["assured"]:
            lines.append(f"**Controls v1 → {r['assured_v1'].upper()}** {mark(r['assured_v1'])}")
        lines.append(f"**AI + controls → {r['assured'].upper()}** {mark(r['assured'])}")
        if r.get("gate_reasons"):
            lines += ["**Why the controls stepped in:**"] + [f"- {g}" for g in r["gate_reasons"][:5]]
        chk = r.get("check_final") or {}
        if chk:
            lines.append(f"Evidence check: {chk.get('verified_observed', 0)} of {chk.get('observed', 0)} observed claims "
                         f"verified" + (f"; failed: {chk['failures'][0][:140]}" if chk.get("failures") else ""))
        return "\n".join(lines)

    # ---------------------------------------------------------------- commands
    def answer(self, msg: str) -> str:
        text = (msg or "").strip()
        low = text.lower()
        if not text or low in ("help", "?", "hi", "hello", "start"):
            return __doc__.split("Things you can type")[1].replace("(case and wording are forgiving):", "**You can type:**\n```") + "```"
        if low.startswith("live"):
            return self.live(text)
        if "red team" in low or "attack success" in low or low.startswith("asr"):
            return self.red_team()
        if "scoreboard" in low or "score" == low or "results" in low:
            return self.scoreboard(low)
        if low.startswith("list"):
            return self.listing(low)
        iid = self._inc(text)
        if not iid:
            return "Which incident? Try `INC-0006`, `list injected`, or `help`."
        if "case" in low:
            return self.casefile(iid)
        if "critic" in low:
            return self.critic(iid)
        if "false positive" in low or "fp" in low.split() or "colleague" in low or "framing" in low:
            run = self._first("fp_framing")
            return self._run_view(iid, run, "When a colleague asks *\"I think this is a false positive, can you confirm?\"*")
        if "agent" in low or "investigat" in low or "tools" in low:
            run = self._first("agentic", "agentic_critic")
            out = self._run_view(iid, run, "When the AI investigates with its own tools")
            r = self.runs.get(run, {}).get(iid)
            if r and r.get("trajectory"):
                steps = " → ".join(f"`{t['tool']}`" for t in r["trajectory"])
                out += f"\n\n**Tools it called:** {steps}"
            return out
        for name, label in (("poison", "poisoned_rag"), ("no playbook", "no_playbook"), ("payload", "payload_only"),
                            ("no context", "no_context"), ("no rag", "no_rag"), ("14b", None)):
            if name in low:
                run = label or next((n for n in self.runs if n.startswith("main__")), None)
                return self._run_view(iid, run, f"Run `{run}`")
        return self._run_view(iid, self._first("main", "main_critic"), "Normal triage")

    def _run_view(self, iid: str, run: str | None, title: str) -> str:
        if not run or iid not in self.runs.get(run, {}):
            return f"No saved `{run or 'run'}` result for {iid} yet."
        return f"*{title}*\n\n" + self._decision(self.runs[run][iid], iid, run)

    def critic(self, iid: str) -> str:
        for run in ("agentic_critic", "main_critic"):
            r = self.runs.get(run, {}).get(iid)
            if r and r.get("critic_review"):
                cr = r["critic_review"]
                return (f"### Critic on {iid} (`{run}`)\n{self._truth_line(iid)}\n\nThe AI wanted to **close**; a second AI "
                        f"argued it might be an attack.\n\n**{'Objects' if r.get('critic_objection_valid') else 'No valid objection'}:** "
                        f"{cr.get('argument', '')[:300]}")
        return f"The critic only reviews **close** decisions; the AI escalated {iid}, so there was nothing to review."

    def casefile(self, iid: str) -> str:
        for run in ("main", "main_critic", "agentic"):
            f = path("results_dir") / "cases" / run / f"{iid}.md"
            if f.exists():
                return f.read_text(encoding="utf-8")[:3500]
        return f"No case file for {iid}. Run `python -m triage_lab cases` first."

    def listing(self, low: str) -> str:
        if "attack" in low or "benign" in low:
            want = "attack" in low
            ids = [i for i, t in self.truth.items() if t["malicious"] == want]
            return f"**{'Attacks' if want else 'Benign incidents'} ({len(ids)}):** " + ", ".join(i[-4:] for i in ids)
        for word, variants in LIST_WORDS.items():
            if word in low:
                ids = [i for i, t in self.truth.items() if t["variant"] in variants]
                return f"**{word} ({len(ids)}):** " + ", ".join(f"{i} ({LABELS.get(self.truth[i]['variant'])})" for i in ids)
        return "List what? " + ", ".join(sorted(LIST_WORDS)) + ", attacks, benign"

    def scoreboard(self, low: str) -> str:
        tri = self.metrics.get("triage", {})
        run = next((n for n in tri if n in low.split()), None) or ("main" if "main" in tri else next(iter(tri), None))
        if not run:
            return "No scored runs yet. Run `python -m triage_lab score`."
        t = tri[run]
        rows = [("", "AI alone", "Controls v1", "Controls v2")]
        arms = [t["baseline"], t.get("assured_v1", t["assured"]), t["assured"]]
        for label, key in (("Real attacks missed", "fn"), ("Recall", "recall"), ("Precision", "precision"),
                           ("F2", "f2"), ("Sent to a human", "escalation_rate")):
            rows.append((label, *(str(a.get(key)) for a in arms)))
        table = "\n".join("| " + " | ".join(r) + " |" for r in rows[:1]) + "\n|---|---|---|---|\n" + \
            "\n".join("| " + " | ".join(r) + " |" for r in rows[1:])
        return f"### Scoreboard · `{run}` · {t['incidents']} incidents\n{table}\n\nRuns available: " + \
            ", ".join(f"`{n}`" for n in tri)

    def red_team(self) -> str:
        rows = self.metrics.get("attack_success") or []
        if not rows:
            return "No red-team results yet. Run `python -m triage_lab score`."
        lines = ["### Red team: attack success rate (lower is better)", "| Attack | Run | AI alone | Controls |", "|---|---|---|---|"]
        lines += [f"| {a['attack'][:48]} | {a['run']} | {a['asr_ai_alone']} | "
                  f"{'n/a' if a['asr_controls'] is None else a['asr_controls']} |" for a in rows]
        return "\n".join(lines)

    def live(self, text: str) -> str:
        """Triage one incident right now with the configured model (agent.backend / --backend)."""
        iid = self._inc(text)
        if not iid:
            return "Live triage of which incident? e.g. `live INC-0006` or `live INC-0062 false positive`."
        from .agent import Agent
        from .context import Baseline
        from .correlate import Incident
        from .evidence import load_user_context
        from .pipeline import _triage_one, detection_stage
        from .rag import Retriever
        if self._live is None:
            events, lq, alerts, incidents = detection_stage()
            self._live = dict(events=events, lq=lq, alerts={a.id: a for a in alerts}, incs={i.id: i for i in incidents},
                              by_id={e.id: e for e in events}, users=load_user_context(), baseline=Baseline(events))
        L = self._live
        agent = Agent(self.backend)
        framing = "false positive" in text.lower()
        if agent.backend == "langflow":
            agent.flow = agent.lf_flows.get("rag")
        row = _triage_one(L["incs"][iid], agent, "evidence", True, True, False, False, 1, L["events"], L["by_id"],
                          L["alerts"], L["lq"], L["users"], None if agent.backend == "langflow" else Retriever(),
                          "live", L["baseline"], framing)
        return (f"*Live answer from `{agent.label}` in {row['seconds']} s"
                + (" (with the leading question)" if framing else "") + "*\n\n" + self._decision(row, iid, "live"))


def serve(port: int = 8765, backend: str | None = None) -> None:
    lab = Lab()
    lab.backend = backend

    class Handler(BaseHTTPRequestHandler):
        def _send(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                msg = data.get("message") or data.get("input_value") or data.get("q") or ""
                self._send({"text": lab.answer(str(msg))})
            except Exception as exc:                      # keep the demo alive whatever happens
                self._send({"text": f"Lab error: {exc}"})

        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query).get("q", ["help"])[0]
            self._send({"text": lab.answer(q)})

        def log_message(self, *a):
            pass

    print(f"Triage lab chat on http://localhost:{port}/ask  ({len(lab.runs)} runs, {len(lab.incidents)} incidents). "
          f"Ctrl+C to stop.")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
