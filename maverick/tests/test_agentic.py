"""Agentic tools, critic parsing and resumable runs."""

from datetime import datetime, timedelta, timezone

from triage_lab.agent import parse_critique, stub_critique
from triage_lab.agentic import Toolbox, _text_tool_call
from triage_lab.correlate import Incident
from triage_lab.log_quality import LogQuality
from triage_lab.schema import Event

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def ev(i, minutes, user="bob.smith", host="WS-BOB", source="endpoint", etype="process_create", **f):
    t = T0 + timedelta(minutes=minutes)
    return Event(f"E{i}", t.isoformat(), (t + timedelta(seconds=5)).isoformat(), source, etype, user, host,
                 "203.0.113.9", {"image": "x.exe", "cmdline": "x", **f})


EVENTS = [ev(1, -300), ev(2, -20), ev(3, 0), ev(4, 10, user="alice.ng", host="WS-ALICE"), ev(5, 15)]
INC = Incident("INC-T", "bob.smith", EVENTS[2].ts, EVENTS[2].ts, ["A1"], ["DET-004"], ["T1069.002"], [4],
               True, 0.3, ["E3"])


def box(context=True):
    lq = LogQuality(EVENTS, {"errors_by_source": {}})
    users = {"bob.smith": {"user": "bob.smith", "role": "Sales", "privileged": "no"}}
    return Toolbox(INC, EVENTS, {e.id: e for e in EVENTS}, lq, users, None, context)


def test_search_events_is_limited_to_the_incident_neighbourhood():
    b = box()
    res = b.call("search_events", {"user": "bob.smith", "minutes_before": 60, "minutes_after": 60})
    assert [e["id"] for e in res["events"]] == ["E2", "E3", "E5"]        # E1 is 5 hours earlier
    assert set(b.seen) == {"E2", "E3", "E5"}


def test_time_window_is_capped():
    res = box().call("search_events", {"user": "bob.smith", "minutes_before": 100000})
    assert "E1" not in [e["id"] for e in res["events"]]                   # cap is 180 minutes


def test_unavailable_and_unknown_tools_return_errors():
    assert "error" in box(context=False).call("lookup_user", {"user": "bob.smith"})
    assert "error" in box().call("delete_logs", {})
    assert "error" in box().call("search_knowledge", {"query": "x"})     # RAG off in this toolbox


def test_lookup_user_and_bad_arguments():
    b = box()
    assert b.call("lookup_user", {"user": "bob.smith"})["record"]["role"] == "Sales" and b.used_context
    assert "error" in b.call("search_events", {"limit": "lots"})


def test_text_tool_call_is_understood_but_verdicts_are_not_tools():
    assert _text_tool_call('{"tool": "log_health", "arguments": {"source": "cloud"}}')[0]["function"]["name"] == "log_health"
    assert _text_tool_call('{"decision": "close", "verdict": "x"}') is None


def test_critique_parsing():
    assert parse_critique('{"objection": true, "argument": "a", "event_ids": ["E1"], "quote": "x"}')["objection"]
    assert parse_critique('{"objection": "maybe"}') is None
    assert stub_critique({"alerts": [{"event_ids": ["E1"]}], "events": [{"id": "E1", "event_type": "x"}]},
                         {})["objection"] is False


def test_resume_skips_finished_incidents(tmp_path, monkeypatch):
    from triage_lab import config
    from triage_lab.generate import main as generate
    from triage_lab.pipeline import run
    monkeypatch.setitem(config.settings()["paths"], "results_dir", str(tmp_path / "results"))
    if not (config.path("data_dir") / "events.jsonl").exists():
        generate()
    first = run("resume_test", "stub", limit=3, quiet=True)
    again = run("resume_test", "stub", limit=5, quiet=True, resume=True)
    assert [r["incident_id"] for r in again[:3]] == [r["incident_id"] for r in first]
    assert len(again) == 5


# ---------------------------------------------------------------- relevance context + case files
def test_baseline_flags_first_seen_and_repeats():
    from triage_lab.context import Baseline
    def obj(i, days_before, ua):
        t = T0 - timedelta(days=days_before)
        return Event(f"B{i}", t.isoformat(), t.isoformat(), "cloud", "object_access", "alice.ng", None, "1.1.1.1",
                     {"bucket": "finance-reports", "user_agent": ua, "operation": "GetObject"})
    hist = [obj(1, 3, "Microsoft Excel")]
    now_excel, now_script = obj(2, 0, "Microsoft Excel"), obj(3, 0, "python-requests/2.31")
    b = Baseline(hist + [now_excel, now_script]).for_incident("alice.ng", T0, [now_excel, now_script])
    seen = {c["event_id"]: c["seen_before"] for c in b["first_seen_checks"]}
    assert seen == {"B2": True, "B3": False}


def test_verifier_accepts_baseline_citation(bundle, good_close):
    from triage_lab.verifier import verify
    bundle["baseline"] = {"first_seen_checks": [{"value": "finance-reports / Microsoft Excel", "seen_before": True}]}
    good_close["claims"].append({"type": "observed", "text": "routine for her", "event_ids": ["BASELINE"],
                                 "quote": "finance-reports / Microsoft Excel"})
    assert verify(good_close, bundle)["passed"]


def test_crown_jewel_first_seen_blocks_close(bundle, good_close):
    from triage_lab.gates import apply_gates
    from triage_lab.verifier import verify
    bundle["gate_context"] = {"assets": {"finance-reports": {"crown_jewel": "yes"}},
                              "baseline": {"first_seen_checks": [{"value": "finance-reports / python-requests",
                                                                  "seen_before": False}]}}
    decision, reasons = apply_gates(good_close, verify(good_close, bundle), bundle)
    assert decision == "escalate" and any("crown-jewel" in r for r in reasons)
    bundle["gate_context"]["baseline"]["first_seen_checks"][0]["seen_before"] = True
    assert apply_gates(good_close, verify(good_close, bundle), bundle)[0] == "close"


def test_case_file_renders():
    from triage_lab.casefile import render
    row = {"incident_id": "INC-T", "assured": "escalate", "user": "bob.smith", "run": "main", "backend": "stub",
           "mode": "evidence", "model_decision": "close", "verdict": "false_positive", "model_confidence": 0.8,
           "gate_reasons": ["privileged identity: never auto-closed"], "summary": "s",
           "claims_final": [{"type": "observed", "text": "t", "event_ids": ["E1"], "quote": "q"}],
           "check_final": {"verified_observed": 1, "observed": 1, "observation_ratio": 1.0},
           "assets_touched": {"WS-BOB": {"type": "workstation", "owner": "bob", "criticality": "low"}},
           "first_seen": [], "alternative_hypothesis": "h", "not_determinable": ["cloud logs"], "log_health": {}}
    md = render(row, {"start": "a", "end": "b", "risk": 0.3, "techniques": ["T1530"], "rules": ["DET-005"]})
    assert "# INC-T: ESCALATE" in md and "privileged identity" in md and "- [ ] cloud logs" in md
