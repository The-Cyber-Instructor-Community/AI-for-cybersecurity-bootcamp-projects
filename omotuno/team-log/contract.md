# Contract — Sift Capstone Iteration 3 (Multi-Agent Layer)

Status: **Approved to Build**  
Date: 2026-07-07  
Scope: **Iteration 3 only** (drift detection, singleton escalation, recalibration proposal + human approval)

## User Goal (verbatim fidelity)

Add Iteration 3 capabilities:
- Drift detection agent monitoring intra-cluster spread and flagging drifted clusters
- Singleton escalation agent classifying novel singletons vs routine noise with reasoning
- Threshold recalibration agent reading disposition history and proposing updated similarity threshold and window values for human approval before anything changes

Success condition:
- a synthetically drifted cluster is flagged by the drift agent
- a novel singleton is escalated with reasoning
- a recalibration proposal is generated and held for human approval rather than applied automatically

## In Scope (Iteration 3)

- Additive Iteration 3 logic and orchestration on top of existing Iteration 1+2.
- Drift detection outputs (advisory flags/reasons/evidence).
- Singleton escalation outputs (novel/routine + reasoning).
- Recalibration proposal generation from reviewed disposition history.
- Human approval gate for proposals (approve/reject state transition).
- Dashboard/view-model visibility for Iteration 3 outputs.
- Full regression protection for Iteration 1+2 behavior.

## Out of Scope

- Automatic remediation or autonomous parameter updates.
- Iteration 4+ behavior.
- Real data ingestion (synthetic Wazuh SSH scope remains).
- Reworking Iteration 1/2 architecture beyond additive integration points.

## Architecture decision

- Keep `run_iteration2.py` stable.
- Add `run_iteration3.py` as a dedicated entrypoint that composes Iteration 2 flow + Iteration 3 agents.
- Add new focused modules for drift/singleton/recalibration logic; keep existing modules minimally touched.

## Contract clarifications (resolved from planning)

1. **Drift threshold boundary:** `drift_score >= DRIFT_THRESHOLD` means flagged.
2. **Drift minimum evidence:** no drift flag for clusters with member count `< 3` (insufficient evidence).
3. **Drift advisory-only:** drift detection must not auto-split or mutate cluster membership/disposition.
4. **Singleton rubric:** deterministic default rubric with explicit labels (`novel`, `routine`) and reasoning string from observed fields/context only.
5. **No auto-escalation:** singleton escalation signal must not auto-write ADR-007 `escalated` disposition nor auto-create external ticket.
6. **Proposal direction policy:** split-heavy evidence should propose stricter clustering; merge-heavy evidence should propose looser clustering.
7. **Proposal bounds:** enforce configured safe bounds for threshold/window; clamp and record that clamping occurred.
8. **Human approval gate:** proposal generation is always `pending_approval`; only explicit approve action may activate proposed values.
9. **Reviewed-only history:** recalibration uses reviewed disposition history, not unresolved/unreviewed clusters.

## Implementation Checklist

### A) Types/state
- [ ] Extend types with Iteration 3 fields (drift, singleton escalation, recalibration proposal state).
- [ ] Add result type for Iteration 3 run output.

### B) Drift detection agent
- [ ] Add deterministic drift agent module.
- [ ] Compute drift score/evidence from cluster spread behavior.
- [ ] Apply minimum-evidence rule (`count < 3` => insufficient evidence/no flag).
- [ ] Set advisory flag + reason/evidence only (no autonomous remediation).

### C) Singleton escalation agent
- [ ] Add deterministic singleton escalation module.
- [ ] Classify singleton as `novel` vs `routine`.
- [ ] Provide concise reasoning tied to observable inputs.
- [ ] Ensure no automatic escalation disposition/ticket writing.

### D) Recalibration proposal agent
- [ ] Add proposal generator module using reviewed disposition history.
- [ ] Propose threshold/window updates with rationale and evidence counts.
- [ ] Enforce safe bounds and capture clamping metadata.
- [ ] Store proposals with `pending_approval` status by default.

### E) Approval gate
- [ ] Add explicit approve/reject transition API.
- [ ] Require reviewer identity and timestamp.
- [ ] Approval applies proposal to active calibration state.
- [ ] Rejection never applies values.
- [ ] Record old/new values and decision audit metadata.

### F) Store/query integration
- [ ] Extend review store with read/query methods needed by recalibration logic.
- [ ] Keep existing action logging behavior intact.

### G) Iteration 3 orchestration
- [ ] Add `run_iteration3.py` entrypoint:
  - [ ] run Iteration 2 flow,
  - [ ] drift evaluation,
  - [ ] singleton escalation evaluation,
  - [ ] recalibration proposal generation,
  - [ ] no automatic parameter update.

### H) Dashboard/view model
- [ ] Add Iteration 3 output visibility:
  - [ ] drift flags/scores/reasons,
  - [ ] singleton escalation labels/reasoning,
  - [ ] proposal status and current/proposed params,
  - [ ] approve/reject action descriptors.
- [ ] Preserve Iteration 2 keys/semantics (backward compatible).

## Required Test Checklist

### Unit
- [ ] Drift true-positive test on synthetic chained drift.
- [ ] Drift false-positive control on coherent cluster.
- [ ] Drift threshold boundary and minimum-evidence tests.
- [ ] Singleton novel vs routine classification tests.
- [ ] Singleton reasoning faithfulness tests (no hallucinated/hidden-label facts).
- [ ] Recalibration proposal direction tests (split-heavy vs merge-heavy history).
- [ ] Recalibration weak/mixed-evidence no-op or low-confidence test.
- [ ] Proposal bounds/clamping tests.
- [ ] Approval gate tests (pending default, approve applies, reject does not).

### Integration
- [ ] Iteration 3 end-to-end pipeline test including drift + singleton + proposal outputs.
- [ ] Combined scenario test proving:
  - [ ] drift flag appears for drifted cluster,
  - [ ] novel singleton escalates with reasoning,
  - [ ] proposal remains pending until approval.
- [ ] Iteration 2 regression controls remain intact in combined runs (suppression-before-embed + contradiction behavior).

### E2E/dashboard
- [ ] Dashboard Iteration 3 test for drift/singleton/proposal visibility.
- [ ] Proposal approval state rendering test (pending vs approved/rejected).
- [ ] Iteration 2 dashboard states remain visible/consistent.

### Full verification
- [ ] `pytest -q` passes.
- [ ] `python -m pip install -q -r requirements.txt && pytest -q` passes.
- [ ] No default test requires live cloud credentials.

## Non-negotiable guardrails

- No automatic threshold/window updates without explicit human approval.
- Synthetic Wazuh SSH scope only.
- Do not regress Iteration 2 safety controls (suppression-before-embed, injection contradiction handling, review queue integrity).
- No Iteration 4 scope creep in this iteration.