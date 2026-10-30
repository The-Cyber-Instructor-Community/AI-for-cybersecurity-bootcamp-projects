"""Investigation grading, decoy scenarios and the prompt variants from the agentic-SOC article."""

import json

from triage_lab.agent import FP_FRAMING_NOTE, NO_PLAYBOOK_PROMPT, SYSTEM_PROMPT, render_prompt, system_prompt
from triage_lab.grading import Judge, grade_row
from triage_lab.schema import Event, load_events


def _ev(i, source, user="bob.smith", src_ip=None, **fields):
    return Event(id=i, ts="2026-10-01T01:00:00+00:00", ingest_ts="2026-10-01T01:00:05+00:00", source=source,
                 event_type="x", user=user, src_ip=src_ip, fields=fields)


EVENTS = {
    "E1": _ev("E1", "email", sender_domain="docs-share.io", url="https://docs-share.io/login"),
    "E2": _ev("E2", "identity", src_ip="203.0.113.7", country="RO"),
    "E3": _ev("E3", "cloud", src_ip="203.0.113.7", bucket="finance-reports"),
    "D1": _ev("D1", "email", sender_domain="vendor-weekly.com", url="https://news.vendor-weekly.com/issue/1"),
    "B1": _ev("B1", "endpoint", parent_image="C:\\Program Files\\Microsoft VS Code\\Code.exe"),
}
LABELS = {
    "E1": {"event_id": "E1", "scenario_id": "S1", "malicious": True, "technique": "T1566.002", "observed": True},
    "E2": {"event_id": "E2", "scenario_id": "S1", "malicious": True, "technique": "T1078.004", "observed": True},
    "E3": {"event_id": "E3", "scenario_id": "S1", "malicious": True, "technique": "T1530", "observed": True},
    "D1": {"event_id": "D1", "scenario_id": "S1", "malicious": False, "technique": None, "decoy": True},
    "B1": {"event_id": "B1", "scenario_id": "S2", "malicious": False, "technique": None},
}
BY_SC = {"S1": [LABELS[k] for k in ("E1", "E2", "E3", "D1")], "S2": [LABELS["B1"]]}
ATTACK = {"malicious": True, "variant": "with_decoy", "scenario_id": "S1"}
BENIGN = {"malicious": False, "variant": "dev_encoded_ps", "scenario_id": "S2"}


def _row(decision, claims, summary=""):
    return {"incident_id": "INC-1", "final_model_decision": decision, "claims_final": claims, "summary": summary,
            "bundle_event_ids": list(EVENTS)}


def _obs(text, eid, quote):
    return {"type": "observed", "text": text, "event_ids": [eid], "quote": quote}


def test_wrong_disposition_is_a_hard_fail():
    g = grade_row(_row("close", [_obs("click", "E1", "docs-share.io")]), ATTACK, BY_SC, LABELS, EVENTS, Judge())
    assert g["hard_fail"] and g["score"] == 0.0 and g["score_before_hard_fail"] > 0


def test_later_stages_weigh_more_and_iocs_count():
    early = grade_row(_row("escalate", [_obs("click", "E1", "docs-share.io")]), ATTACK, BY_SC, LABELS, EVENTS, Judge())
    late = grade_row(_row("escalate", [_obs("bulk read", "E3", "finance-reports")], "from 203.0.113.7"),
                     ATTACK, BY_SC, LABELS, EVENTS, Judge())
    assert late["score"] > early["score"]
    assert any(x["gate"] == "attacker IP stated" and x["passed"] for x in late["gates"])


def test_misquoted_claim_is_flagged_not_credited():
    g = grade_row(_row("escalate", [_obs("bulk read", "E3", "hr-records")]), ATTACK, BY_SC, LABELS, EVENTS, Judge())
    assert len(g["wrong_claims"]) == 1
    assert not any(x["passed"] for x in g["gates"] if x["gate"].startswith("T1530"))


def test_decoy_presented_as_attack_is_misattribution():
    bad = grade_row(_row("escalate", [_obs("phishing click on lure", "D1", "vendor-weekly.com")]),
                    ATTACK, BY_SC, LABELS, EVENTS, Judge())
    ok = grade_row(_row("escalate", [_obs("separate legitimate newsletter click", "D1", "vendor-weekly.com")]),
                   ATTACK, BY_SC, LABELS, EVENTS, Judge())
    assert bad["misattributions"] and bad["misattributions"][0]["decoy"]
    assert not ok["misattributions"]
    gate = "legitimate activity kept out of the attack narrative"
    assert [x["passed"] for x in bad["gates"] if x["gate"] == gate] == [False]
    assert [x["passed"] for x in ok["gates"] if x["gate"] == gate] == [True]


def test_benign_close_needs_the_explanation():
    with_why = grade_row(_row("close", [_obs("launched from VS Code", "B1", "Code.exe")]),
                         BENIGN, BY_SC, LABELS, EVENTS, Judge())
    without = grade_row(_row("close", []), BENIGN, BY_SC, LABELS, EVENTS, Judge())
    assert with_why["score"] == 100.0 and without["score"] == 0.0 and not without["hard_fail"]


def test_default_prompt_unchanged_and_variants_differ(bundle):
    assert system_prompt() is SYSTEM_PROMPT
    assert "Asset criticality" in SYSTEM_PROMPT and "Asset criticality" not in NO_PLAYBOOK_PROMPT
    assert "Return ONLY a JSON object" in NO_PLAYBOOK_PROMPT and "State only facts" in NO_PLAYBOOK_PROMPT
    plain = render_prompt(bundle)
    assert "analyst_note" not in plain
    assert render_prompt({**bundle, "analyst_note": FP_FRAMING_NOTE}).startswith(plain)


def test_extra_ingest_batch_keeps_its_own_parse_score(tmp_path):
    good = [json.dumps({"id": f"E{i}", "ts": f"2026-10-01T00:{i:02d}:00+00:00",
                        "ingest_ts": f"2026-10-01T00:{i:02d}:05+00:00", "source": "email", "event_type": "x"})
            for i in range(10)]
    (tmp_path / "events.jsonl").write_text("\n".join(good + ['{"source": "email", broken']) + "\n")
    (tmp_path / "events_decoy.jsonl").write_text(json.dumps(
        {"id": "D1", "ts": "2026-10-02T00:00:00+00:00", "ingest_ts": "2026-10-02T00:00:05+00:00",
         "source": "email", "event_type": "x"}) + "\n")
    events, stats = load_events(tmp_path / "events.jsonl")
    assert len(events) == 11 and set(stats["batches"]) == {"events", "events_decoy"}
    assert stats["batches"]["events"]["errors_by_source"] == {"email": 1}
    assert stats["batches"]["events_decoy"]["errors_by_source"] == {}
