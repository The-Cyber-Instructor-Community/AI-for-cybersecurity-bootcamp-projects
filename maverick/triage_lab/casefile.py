"""Handover output: one readable Markdown case file per incident.

What an analyst receives instead of a raw alert: the decision and why, the
verified evidence, what makes it matter (asset + baseline), what the agent
checked, the critic's view, the alternative explanation, and what is still
unknown. Built from saved results only, so it needs no model and no GPU.

    python -m triage_lab cases --run main     ->  results/cases/main/INC-0001.md ...
"""

from __future__ import annotations

from .config import path
from .metrics import incident_truth, load_truth
from .schema import read_jsonl


def _md_escape(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render(r: dict, inc: dict, truth: dict | None = None, grade: dict | None = None) -> str:
    decision = r["assured"].upper()
    lines = [f"# {r['incident_id']}: {decision}",
             "",
             f"**User:** {r['user']}  ·  **Window:** {inc['start']} to {inc['end']}  ·  "
             f"**Risk:** {inc['risk']}  ·  **Techniques:** {', '.join(inc['techniques'])}",
             f"**Detections:** {', '.join(inc['rules'])}  ·  **Run:** {r['run']} ({r['backend']}, mode {r['mode']})",
             "",
             "## Decision",
             f"- **Final (AI + controls):** {decision}",
             f"- **AI recommendation:** {r['model_decision']} ({r.get('verdict') or 'n/a'}, confidence "
             f"{r['model_confidence']})"]
    if r["gate_reasons"]:
        lines.append("- **Why a human must look:**")
        lines += [f"    - {_md_escape(g)}" for g in r["gate_reasons"]]
    lines += ["", "## Summary", r.get("summary") or "_no summary_", ""]

    claims = [c for c in r.get("claims_final") or [] if isinstance(c, dict)]
    obs = [c for c in claims if c.get("type") == "observed"]
    inf = [c for c in claims if c.get("type") != "observed"]
    chk = r.get("check_final") or {}
    lines += [f"## Evidence ({chk.get('verified_observed', 0)} of {chk.get('observed', 0)} observed claims verified, "
              f"observation ratio {chk.get('observation_ratio', 0)})"]
    if obs:
        lines += ["| Observed | Source | Quote |", "|---|---|---|"]
        lines += [f"| {_md_escape(c.get('text'))} | {', '.join(c.get('event_ids') or [])} | `{_md_escape(c.get('quote'))}` |"
                  for c in obs]
    if inf:
        lines += ["", "**Inferred:**"] + [f"- {_md_escape(c.get('text'))}" for c in inf]
    if chk.get("failures"):
        lines += ["", "**Claims that failed verification:**"] + [f"- {_md_escape(f)}" for f in chk["failures"]]

    lines += ["", "## Why it matters"]
    assets = r.get("assets_touched") or {}
    for name, rec in assets.items():
        jewel = " **(crown jewel)**" if rec.get("crown_jewel") == "yes" else ""
        lines.append(f"- **{name}**{jewel}: {rec.get('type')}, owner {rec.get('owner')}, criticality "
                     f"{rec.get('criticality')}. {rec.get('notes', '')}")
    if not assets:
        lines.append("- No asset records for the hosts or buckets involved.")
    new = r.get("first_seen") or []
    lines += [f"- **New for this user:** {c['attribute']} = `{c['value']}`" for c in new] or \
             ["- Nothing in this incident is new for this user (seen in the 7-day baseline)."]
    lines.append(f"- AI cited asset or baseline facts: {'yes' if r.get('relevance_cited') else 'no'}")

    if r.get("trajectory"):
        lines += ["", "## What the agent checked"]
        lines += [f"{n}. `{t['tool']}({', '.join(f'{k}={v}' for k, v in t['args'].items())})`"
                  + (f" - error: {t['error']}" if t.get("error") else "")
                  for n, t in enumerate(r["trajectory"], 1)]
    if r.get("critic_review"):
        cr = r["critic_review"]
        lines += ["", "## Reviewer (critic)",
                  f"- {'**Objects**' if r.get('critic_objection_valid') else 'No valid objection'}: "
                  f"{_md_escape(cr.get('argument', ''))}"]
    lines += ["", "## Alternative hypothesis", r.get("alternative_hypothesis") or "_not given_", "",
              "## Next steps for the analyst"]
    nd = r.get("not_determinable") or []
    lines += [f"- [ ] {_md_escape(x)}" for x in nd] or ["- [ ] Confirm the AI's evidence above and close or escalate."]
    lh = r.get("log_health") or {}
    weak = [f"{s} ({v})" for s, v in lh.items() if v < 0.6]
    if weak:
        lines.append(f"- [ ] Check the log pipeline: {', '.join(weak)} looked unhealthy in this window.")
    if truth:
        lines += ["", "---", f"_Lab answer key (not visible to an analyst): "
                             f"{'MALICIOUS' if truth['malicious'] else 'benign'}, scenario {truth['variant']}._"]
    if grade:
        verdict = "HARD FAIL (wrong disposition)" if grade["hard_fail"] else f"{grade['score']}/100"
        lines += [f"_Investigation score: {verdict}. Gates: "
                  + "; ".join(f"{'✓' if g['passed'] else '✗'} {g['gate']} ({g['weight']})" for g in grade["gates"])
                  + "._"]
        if grade["misattributions"]:
            lines.append("_Misattributed (legitimate activity presented as the attack): "
                         + ", ".join(m["event_id"] + (" (decoy)" if m["decoy"] else "") for m in grade["misattributions"])
                         + "._")
    return "\n".join(lines) + "\n"


def write_cases(run_name: str) -> int:
    rows = list(read_jsonl(path("results_dir") / "runs" / f"{run_name}.jsonl"))
    incs = {i["id"]: i for i in read_jsonl(path("results_dir") / "pipeline" / "incidents.jsonl")}
    _, by_event, scenarios = load_truth()
    from .grading import load_grades
    grades = load_grades(run_name)
    out = path("results_dir") / "cases" / run_name
    out.mkdir(parents=True, exist_ok=True)
    for r in rows:
        inc = incs.get(r["incident_id"])
        if inc:
            truth = incident_truth(inc, by_event, scenarios)
            (out / f"{r['incident_id']}.md").write_text(render(r, inc, truth, grades.get(r["incident_id"])),
                                                       encoding="utf-8")
    return len(rows)
