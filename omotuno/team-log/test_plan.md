# Sift Iteration 3 Adversarial Test Plan

Date: 2026-07-06  
Role: Evaluator for Iteration 3 planning only  
Scope: Iteration 3 only — drift detection agent, singleton escalation agent, and threshold/window recalibration proposal workflow with strict human approval.

Assumption: the Iteration 3 implementation is broken until proven otherwise.

Note: `Sift_Capstone_Requirements.md` is not present in the current working tree at evaluation time. This plan uses the previously established Sift requirements/ADRs, current `README.md`, current Iteration 1+2 code/tests, and the documented Iteration 3 scope:
- drift detection agent,
- singleton escalation agent,
- recalibration proposal agent,
- human approval gate for recalibration,
- no autonomous threshold/window changes.

Strictly in scope:
- Drift detection behavior, including true-positive and false-positive controls.
- Singleton escalation classification and reasoning quality.
- Recalibration proposal generation from analyst disposition history.
- Human approval gate that prevents automatic parameter updates.
- Integration with existing Iteration 1+2 behavior without regression.

Strictly out of scope:
- New suppression semantics beyond Iteration 2 regression protection.
- New prompt-injection features beyond Iteration 2 regression protection.
- Autonomous remediation.
- Automatic threshold/WINDOW updates without explicit human approval.
- Multi-source normalization.
- Real alert data.

---

## 1) Existing harness touchpoints

Current harness and implementation provide these Iteration 3 touchpoints:

- `pytest` suite:
  - `tests/unit/`
  - `tests/integration/`
  - `tests/e2e/`
  - `tests/fixtures/`

- Existing Iteration 1+2 regression anchors:
  - synthetic Wazuh SSH alert ingestion and validation,
  - deterministic embedding adapter,
  - deterministic summary adapter,
  - ADR-003 time-window prefilter,
  - ADR-004 centroid update,
  - ADR-006 summary payload,
  - ADR-007 review actions and audit store,
  - ADR-008 prompt-injection backstop,
  - stale summary cache behavior,
  - dashboard view model.

- Existing state/data structures:
  - `ClusterState` has members, centroid, count, first_seen, last_seen, summary, review/disposition fields, supersession fields, contradiction fields, stale summary fields.
  - `Iteration2Result` has clusters, singletons, review queue, suppressed/embedded counts.
  - `InMemoryReviewStore` and `SQLiteReviewStore` log review audit entries with action metadata.

Expected Iteration 3 additions/seams:

- Drift detection module/agent:
  - likely new `src/agents/drift_agent.py` or `src/logic/drift_detection.py`.
  - consumes cluster members and/or member embeddings/spread data.
  - produces drift score, drift flag, reason, and evidence fields.
  - must not replace ADR-003/ADR-004 clustering behavior unless explicitly approved.

- Singleton escalation module/agent:
  - consumes singleton clusters/alerts and recent cluster context.
  - classifies singleton as escalate vs routine/no-escalation.
  - produces concise evidence-based reasoning.
  - must be deterministic in default tests via stubbed client/judge.

- Recalibration proposal module/agent:
  - consumes disposition/review history, especially split/merge/confirm/dismiss/escalate.
  - proposes threshold/WINDOW adjustments.
  - produces rationale, evidence counts, expected effect, and risk notes.
  - proposal must be inert until human approval.

- Human approval gate:
  - displays recalibration proposals.
  - supports approve/reject.
  - records reviewer and reviewed_at.
  - parameter updates only occur after explicit approval.

- Dashboard view-model additions:
  - drift flags/reasons.
  - singleton escalation priority/reasoning.
  - recalibration proposal queue.
  - approval status and action descriptors.
  - current vs proposed threshold/WINDOW.

---

## 2) Required unit/integration/e2e tests for Iteration 3

### Unit tests

#### U3-01 — Drift detector true positive on synthetic chained drift

Purpose: prove drift detection catches the known ADR-004 limitation: chaining drift within an active window.

Setup:
- Cluster with founding members from one semantic pattern.
- Later members gradually shift to another pattern.
- Each join may be individually plausible, but final spread from founding members is high.
- Use deterministic vectors with known distances.

Assertions:
- Drift score exceeds configured threshold.
- `drift_detected == True`.
- Reason code includes `CENTROID_DRIFT` or equivalent.
- Evidence includes at least:
  - founding/early reference,
  - farthest member or spread statistic,
  - threshold used.
- Detection does not mutate cluster membership, centroid, count, or disposition.

Failure:
- Only checking last alert vs current centroid and missing the chain fails.

#### U3-02 — Drift detector false positive control on coherent burst

Purpose: prove drift detector does not flag normal SSH brute-force variation.

Setup:
- Cluster with many same-incident alerts.
- Minor port/user/log wording variations.
- All alerts share same ground-truth incident ID.

Assertions:
- Drift score remains below threshold.
- `drift_detected == False`.
- No escalation/review override is created.
- Existing Iteration 1 cluster purity remains unchanged.

#### U3-03 — Drift detector boundary behavior

Purpose: make threshold behavior measurable.

Setup:
- Drift score exactly equal to threshold.
- Drift score just below threshold.
- Drift score just above threshold.

Assertions:
- Exact-boundary behavior is documented and asserted.
- Just-below does not flag.
- Just-above flags.
- Floating point tolerance is explicit.

#### U3-04 — Drift detector requires enough evidence

Purpose: prevent noisy flags on tiny clusters.

Setup:
- Singleton cluster.
- Two-alert cluster.
- Cluster below minimum evidence count.

Assertions:
- Detector returns `insufficient_evidence` or no flag.
- No drift alert is emitted for singleton by drift detector.
- Singleton escalation remains separate.

#### U3-05 — Drift detector ignores closed/superseded clusters unless configured

Purpose: avoid stale/irrelevant drift flags.

Setup:
- Closed cluster.
- Split/merged superseded cluster.
- Active cluster.

Assertions:
- Closed/superseded handling is documented.
- If skipped, reason is `not_active` or equivalent.
- Active cluster is evaluated.
- No superseded cluster re-enters active review queue due to drift flag.

#### U3-06 — Singleton escalation: malicious/novel singleton true positive

Purpose: prove singleton escalation can identify high-priority novel singleton.

Setup:
- Singleton alert with unusual SSH auth pattern, new source IP, rare username, or high-risk text.
- Recent cluster context contains routine brute-force clusters.

Assertions:
- Classification is `escalate` or `high_priority`.
- Reasoning cites concrete fields from the singleton and/or context.
- Reasoning does not invent facts.
- Output includes confidence/priority score if implemented.
- Cluster enters review/escalation queue without auto-escalating to external ticket unless human action is explicit.

#### U3-07 — Singleton escalation: routine singleton false positive control

Purpose: prevent alert fatigue from over-escalating every singleton.

Setup:
- Routine one-off SSH failure matching known benign/demo pattern.
- No unusual metadata.

Assertions:
- Classification is `routine` or `no_escalation`.
- Reasoning is concise and evidence-based.
- No escalation disposition is written automatically.
- Singleton remains reviewable but not high-priority.

#### U3-08 — Singleton escalation reasoning quality

Purpose: verify reasoning quality, not just label.

Assertions:
- Reason includes at least one observed fact.
- Reason does not include hidden ground truth labels.
- Reason does not claim unavailable context.
- Reason is bounded in length.
- Reason avoids unsupported severity language unless classification supports it.
- If LLM-as-judge is used, deterministic tests must use a stubbed judge with fixed rubric.

#### U3-09 — Singleton escalation classification boundaries

Purpose: ensure threshold/score behavior is deterministic.

Setup:
- Escalation score below threshold.
- Equal to threshold.
- Above threshold.

Assertions:
- Boundary behavior is documented.
- Above threshold escalates/high-priority.
- Below threshold does not.
- Equal threshold behavior is consistent.

#### U3-10 — Recalibration proposal from split history

Purpose: verify split dispositions produce threshold/WINDOW proposal evidence.

Setup:
- Review history containing multiple split actions indicating false merges.
- Include metadata about cluster sizes, incident IDs if available, and previous threshold/window.

Assertions:
- Proposal recommends a direction consistent with false merges:
  - usually higher similarity threshold and/or shorter WINDOW.
- Proposal cites split action counts and affected clusters.
- Proposal includes proposed threshold/WINDOW values.
- Proposal includes rationale and risks.
- Proposal status is `pending_approval`.
- Current runtime config is unchanged.

#### U3-11 — Recalibration proposal from merge history

Purpose: verify merge dispositions produce proposal evidence.

Setup:
- Review history containing multiple merge actions indicating false splits.

Assertions:
- Proposal recommends a direction consistent with false splits:
  - usually lower similarity threshold and/or longer WINDOW.
- Proposal cites merge action counts and affected clusters.
- Proposal status is `pending_approval`.
- Current runtime config is unchanged.

#### U3-12 — Recalibration mixed evidence / no-op proposal

Purpose: prevent overconfident proposals from weak or conflicting history.

Setup:
- Balanced split and merge history.
- Too few dispositions.
- Mostly confirm/dismiss actions.

Assertions:
- Agent returns `no_change_recommended` or low-confidence proposal.
- Rationale states insufficient/conflicting evidence.
- No threshold/WINDOW change is applied.
- Human approval controls are still inert/no-op if no proposal exists.

#### U3-13 — Recalibration proposal clamps safe bounds

Purpose: prevent unsafe proposed parameter values.

Setup:
- Extreme disposition history that would push threshold below 0 or above 1.
- Extreme WINDOW suggestions below minimum or above maximum.

Assertions:
- Proposed threshold is clamped to documented safe range.
- Proposed WINDOW is clamped to documented safe range.
- Proposal includes a reason that clamping occurred.
- Invalid values are never applied.

#### U3-14 — Human approval gate: no automatic update

Purpose: prove recalibration is proposal-only until approved.

Setup:
- Current config: threshold `T`, WINDOW `W`.
- Recalibration agent generates proposal `T2`, `W2`.

Assertions:
- Current active threshold remains `T`.
- Current active WINDOW remains `W`.
- Proposal is stored/displayed with `pending_approval`.
- No pipeline run uses proposed values before approval.
- Audit log records proposal creation, not application.

#### U3-15 — Human approval gate: approve applies and audits

Purpose: prove explicit human approval is required and recorded.

Setup:
- Pending proposal.
- Reviewer identity and timestamp.

Assertions:
- Approval requires reviewer.
- Approval writes `approved_by`, `approved_at`.
- Active config/calibration state updates only after approval.
- Audit includes old values and new values.
- Re-running approval is idempotent or rejected with documented behavior.

#### U3-16 — Human approval gate: reject does not apply

Purpose: prove rejection preserves current parameters.

Setup:
- Pending proposal.
- Reviewer rejects with reason.

Assertions:
- Proposal status becomes `rejected`.
- Active threshold/WINDOW unchanged.
- Rejection reason, reviewed_by, reviewed_at recorded.
- Rejected proposal cannot later auto-apply.

#### U3-17 — Recalibration history ignores unreviewed/noisy data

Purpose: ensure recalibration uses human labels, not raw cluster guesses.

Setup:
- Review history containing reviewed split/merge/confirm/dismiss/escalate plus unreviewed clusters.
- Include contradiction-detected but unreviewed clusters.

Assertions:
- Proposal evidence uses reviewed dispositions only.
- Unreviewed clusters do not affect recalibration proposal.
- Contradiction-detected but unreviewed clusters do not change parameters.

#### U3-18 — Agent outputs are deterministic in default tests

Purpose: keep CI stable.

Assertions:
- Drift, singleton, and recalibration tests use deterministic stubs/adapters by default.
- No default test requires live Bedrock/cloud credentials.
- Optional live LLM tests are env-gated and excluded from `pytest -q`.

---

### Integration tests

#### I3-01 — Iteration 3 pipeline preserves Iteration 1+2 behavior

Purpose: verify agent additions do not regress existing ingestion, clustering, suppression, backstop, review queue.

Flow:
1. Run existing 200-alert synthetic fixture through Iteration 3 runner.
2. Include no drift/singleton/recalibration triggers or use neutral stubs.

Assertions:
- Raw alert count remains 200.
- Iteration 1 clustering/reduction behavior remains within accepted expectations.
- Iteration 2 suppression-before-embed still occurs when rules exist.
- ADR-008 injection backstop still flags poisoned summaries.
- Review queue still visible.
- Existing `pytest -q` Iteration 1+2 tests continue passing.

#### I3-02 — Drift detection integrated without mutating cluster assignment

Purpose: ensure drift detection is advisory/flagging, not hidden reclustering.

Flow:
- Process a batch with one synthetically drifted cluster.
- Drift agent runs after joins or after cluster finalization.

Assertions:
- Drift flag is attached to cluster.
- Original members remain unchanged.
- No automatic split occurs.
- Review queue/dashboard marks drift for analyst review.
- No Iteration 3 autonomous corrective action is performed.

#### I3-03 — Drift false-positive integration control

Purpose: verify normal clusters remain unflagged in pipeline.

Flow:
- Process coherent brute-force cluster fixture.

Assertions:
- `drift_detected == False`.
- Dashboard does not show drift warning.
- Review queue count is not inflated solely by drift false positives.

#### I3-04 — Singleton escalation integrated with result.singletons

Purpose: verify singleton escalation uses existing singleton output.

Flow:
- Process batch with:
  - routine singleton,
  - novel/high-priority singleton.

Assertions:
- Singleton escalation runs only on singleton clusters.
- High-priority singleton is flagged with reason.
- Routine singleton is not escalated.
- No non-singleton cluster receives singleton escalation state.
- Dashboard shows singleton priority/reason.

#### I3-05 — Recalibration proposal from real review audit store

Purpose: verify proposal agent consumes persisted review history.

Flow:
1. Use `InMemoryReviewStore` or `SQLiteReviewStore`.
2. Log split and merge actions through real review action functions.
3. Run recalibration proposal generator.

Assertions:
- Proposal evidence includes persisted audit actions.
- Split/merge counts match store contents.
- Proposal status is pending.
- Active threshold/WINDOW remain unchanged.

#### I3-06 — Recalibration approval applies only after human approval

Flow:
1. Generate proposal.
2. Run pipeline before approval.
3. Approve proposal.
4. Run pipeline after approval.

Assertions:
- Before approval, runner uses old threshold/WINDOW.
- After approval, runner uses approved threshold/WINDOW if a calibration state store is part of implementation.
- Approval is audited.
- No auto-application occurs at proposal time.

#### I3-07 — Recalibration rejection path

Flow:
1. Generate proposal.
2. Reject proposal.
3. Run pipeline.

Assertions:
- Rejected proposal does not affect active parameters.
- Rejection is audited.
- Dashboard marks proposal rejected.

#### I3-08 — Combined Iteration 3 scenario

Flow:
- Batch includes:
  - coherent cluster,
  - drifted cluster,
  - routine singleton,
  - high-priority singleton,
  - injection payload from Iteration 2,
  - existing suppression rule.
- Review history includes split/merge evidence.

Assertions:
- Suppression still occurs before embed.
- Injection still shows contradiction detected.
- Drifted cluster is flagged.
- Coherent cluster is not drift-flagged.
- High-priority singleton is escalated/flagged.
- Routine singleton is not high-priority.
- Recalibration proposal is generated but pending approval.
- No automatic threshold/WINDOW update occurs.

---

### E2E / dashboard tests

#### E3-01 — Dashboard drift flag visibility

Assertions:
- Drifted cluster row/card includes:
  - drift_detected,
  - drift_score,
  - drift_reason,
  - evidence summary.
- Non-drift cluster does not display drift warning.
- Drift warning does not replace ADR-008 contradiction warning if both states exist; precedence is documented.

#### E3-02 — Dashboard singleton escalation visibility

Assertions:
- Singleton queue/section exists or singleton rows include:
  - singleton_priority,
  - singleton_escalation_label,
  - singleton_reasoning,
  - confidence if implemented.
- High-priority singleton is visually distinguishable.
- Routine singleton is not marked high-priority.

#### E3-03 — Dashboard recalibration proposal visibility

Assertions:
- Dashboard shows pending recalibration proposal.
- Proposal includes:
  - current threshold,
  - proposed threshold,
  - current WINDOW,
  - proposed WINDOW,
  - evidence counts,
  - rationale,
  - risk notes,
  - status.
- Approve/reject action descriptors are present.

#### E3-04 — Dashboard human approval gate

Assertions:
- Before approval, proposed values are not active.
- Approve action requires reviewer.
- Reject action requires reviewer and optional reason.
- After approval, status and audit metadata are visible.
- After rejection, no parameter change is shown as active.

#### E3-05 — Dashboard regression for Iteration 2 states

Assertions:
- Review queue remains visible.
- Contradiction-detected rendering remains correct.
- Stale summary rendering remains correct.
- Five ADR-007 action descriptors remain present.

---

## 3) Edge-case/failure matrix

| ID | Failure mode | Level | Trigger | Expected outcome |
|---|---|---:|---|---|
| EC3-01 | Drift detector misses chained semantic shift | Unit/integration | Gradual shift fixture | Drift flagged with evidence |
| EC3-02 | Drift detector flags normal burst | Unit/integration | Coherent same-incident cluster | No drift flag |
| EC3-03 | Drift threshold boundary ambiguous | Unit | score == threshold | Documented behavior asserted |
| EC3-04 | Drift runs on singleton | Unit | one-member cluster | No drift / insufficient evidence |
| EC3-05 | Drift mutates cluster assignment | Integration | drifted cluster | No membership/centroid mutation beyond normal clustering |
| EC3-06 | Drift auto-splits cluster | Integration | drift flag | Fail; no autonomous split |
| EC3-07 | Singleton escalation flags every singleton | Unit/integration | routine singleton | No high-priority escalation |
| EC3-08 | Singleton escalation misses novel singleton | Unit/integration | high-risk singleton | High-priority/escalate flag |
| EC3-09 | Singleton reasoning hallucinates facts | Unit | stubbed singleton context | Fail reasoning-quality check |
| EC3-10 | Singleton reasoning uses hidden ground truth | Unit | labeled fixture | Fail; labels not in prompt/context |
| EC3-11 | Recalibration uses unreviewed clusters | Unit/integration | unreviewed cluster history | Ignored |
| EC3-12 | Split history proposes lower threshold | Unit | false-merge split-heavy history | Fail; direction wrong |
| EC3-13 | Merge history proposes higher threshold | Unit | false-split merge-heavy history | Fail; direction wrong |
| EC3-14 | Mixed weak history overfits | Unit | balanced/low evidence | No-change or low-confidence proposal |
| EC3-15 | Proposal outside safe bounds | Unit | extreme history | Values clamped/rejected |
| EC3-16 | Proposal auto-applies | Unit/integration/e2e | proposal generated | Active params unchanged |
| EC3-17 | Approval missing reviewer | Unit/e2e | approve without reviewer | Reject |
| EC3-18 | Rejection applies values | Unit/e2e | reject proposal | Active params unchanged |
| EC3-19 | Approved update lacks audit | Unit/integration | approve proposal | Audit old/new values |
| EC3-20 | Rejected proposal later auto-applies | Integration | reject then run | No update |
| EC3-21 | Iteration 2 injection defense regresses | Integration/e2e | poisoned log | Contradiction still displayed |
| EC3-22 | Suppression-before-embed regresses | Integration | active suppression | Suppressed alerts not embedded |
| EC3-23 | Review queue hidden by new dashboard | E2E | Iteration 3 dashboard | Review queue still visible |
| EC3-24 | Live LLM required in default tests | Full suite | `pytest -q` | Fail; default suite must be offline |
| EC3-25 | Iteration 3 changes real data scope | Review | non-synthetic fixture | Reject as out of scope |

---

## 4) Traceability to Iteration 3 requirements

| Test ID | Requirement / planned feature | Proves |
|---|---|---|
| U3-01 | Drift detection agent | True-positive drift detection on chaining |
| U3-02 | Drift detection agent | False-positive control on coherent clusters |
| U3-03 | Drift detection agent | Deterministic threshold behavior |
| U3-04 | Drift detection agent | Minimum-evidence guard |
| U3-05 | Drift detection agent | Closed/superseded clusters handled safely |
| U3-06 | Singleton escalation agent | Novel singleton escalated/flagged |
| U3-07 | Singleton escalation agent | Routine singleton not over-escalated |
| U3-08 | Singleton escalation agent | Reasoning quality and faithfulness |
| U3-09 | Singleton escalation agent | Classification boundary behavior |
| U3-10 | Recalibration agent | Split history produces appropriate proposal direction |
| U3-11 | Recalibration agent | Merge history produces appropriate proposal direction |
| U3-12 | Recalibration agent | Conflicting/weak evidence yields no-change/low confidence |
| U3-13 | Recalibration agent | Safe parameter bounds |
| U3-14 | Human approval gate | Proposal does not auto-apply |
| U3-15 | Human approval gate | Approval applies and audits |
| U3-16 | Human approval gate | Rejection does not apply |
| U3-17 | Recalibration from dispositions | Uses reviewed disposition history only |
| U3-18 | Test reliability | Default tests are deterministic/offline |
| I3-01 | Iteration 1+2 regression protection | Existing behavior intact |
| I3-02 | Drift integration | Drift advisory flag, no autonomous split |
| I3-03 | Drift false-positive control | Normal clusters unflagged end-to-end |
| I3-04 | Singleton integration | Agent runs only on singletons |
| I3-05 | Recalibration integration | Proposal generated from audit store |
| I3-06 | Human approval integration | Approved proposal only then affects active params |
| I3-07 | Human approval integration | Rejected proposal has no effect |
| I3-08 | Combined scenario | Iteration 3 features coexist with Iteration 1+2 controls |
| E3-01 | Dashboard drift visibility | Drift state visible to analyst |
| E3-02 | Dashboard singleton visibility | Singleton priority/reasoning visible |
| E3-03 | Dashboard proposal visibility | Recalibration proposal visible |
| E3-04 | Dashboard approval gate | Human approval/rejection visible and enforced |
| E3-05 | Dashboard regression | Iteration 2 dashboard states retained |

Acceptance traceability checklist:
- Drift detection true positive and false positive controls exist.
- Singleton escalation correctness and reasoning quality are tested.
- Recalibration proposals are generated from reviewed disposition history.
- Recalibration proposals are pending until human approval.
- No automatic parameter update occurs.
- Iteration 1+2 regression tests remain green.

---

## 5) Final validation commands + pass criteria

### Targeted unit tests first

```bash
pytest tests/unit/test_drift_detection.py -q
pytest tests/unit/test_singleton_escalation.py -q
pytest tests/unit/test_recalibration_proposals.py -q
pytest tests/unit/test_recalibration_approval_gate.py -q
```

Pass criteria:
- Drift true-positive fixture is flagged.
- Drift false-positive control is not flagged.
- Drift threshold boundary is explicit.
- Routine singleton is not high-priority.
- Novel singleton is high-priority with faithful reasoning.
- Split-heavy history proposes a false-merge-corrective direction.
- Merge-heavy history proposes a false-split-corrective direction.
- Weak/mixed history yields no-change or low confidence.
- Proposal generation does not update active threshold/WINDOW.
- Approval/rejection paths are audited and deterministic.

Fail criteria:
- Any proposal auto-applies.
- Any singleton reasoning hallucinates facts.
- Any drift detector mutates cluster membership.
- Any default test requires live LLM/cloud access.

### Integration tests

```bash
pytest tests/integration/test_iteration3_pipeline.py -q
pytest tests/integration/test_drift_integration.py -q
pytest tests/integration/test_singleton_escalation_pipeline.py -q
pytest tests/integration/test_recalibration_from_review_history.py -q
pytest tests/integration/test_recalibration_human_approval.py -q
```

Pass criteria:
- Iteration 3 runner preserves Iteration 1+2 behavior.
- Drifted cluster is flagged; normal cluster is not.
- Singleton escalation runs only on singletons.
- Recalibration proposal uses persisted review history.
- Proposal remains pending until approved.
- Rejection does not apply.
- Approval applies only with reviewer and audit.

Fail criteria:
- Suppression-before-embed regresses.
- Injection contradiction rendering regresses.
- Review queue disappears.
- Any threshold/WINDOW update occurs without explicit approval.

### E2E/dashboard tests

```bash
pytest tests/e2e/test_dashboard_iteration3.py -q
```

Pass criteria:
- Drift warning visible with score/reason/evidence.
- Singleton escalation label and reasoning visible.
- Recalibration proposal visible with current/proposed values, rationale, risk notes, and status.
- Approval/rejection controls visible.
- Iteration 2 review queue, contradiction state, stale state, and action descriptors remain visible.

Fail criteria:
- Dashboard hides review queue.
- Dashboard presents proposal as already active before approval.
- Dashboard omits rationale/evidence for escalation or recalibration.

### Full regression suite

```bash
pytest -q
```

Pass criteria:
- All Iteration 1 tests pass.
- All Iteration 2 tests pass.
- All Iteration 3 tests pass.
- No default test requires live Bedrock/cloud credentials.
- Synthetic-only SSH scope remains intact.

### Declared dependency validation

```bash
python -m pip install -q -r requirements.txt
pytest -q
```

Pass criteria:
- Full suite passes after dependency installation.
- Dashboard tests do not depend on missing packages.
- Local persistence tests do not require external services.

### Optional static checks if configured

```bash
ruff check .
ruff format --check .
mypy .
```

Pass criteria:
- No lint/format/type failures if configured.
- If tooling is absent, record as not configured but not a functional failure.

### Optional non-interactive smoke command

If an Iteration 3 runner exists:

```bash
python -m src.pipeline.run_iteration3 --input <synthetic_iteration3_fixture> --no-live-llm
```

Pass criteria:
- Command exits zero.
- Output includes:
  - raw alert count,
  - cluster count,
  - drift-detected count,
  - singleton escalation count,
  - recalibration proposal count,
  - proposal approval status,
  - active threshold/WINDOW values.
- Proposal status is pending unless explicit approval input is supplied.
- Existing Iteration 2 contradiction/review queue states remain present.

---

## Final Iteration 3 acceptance gate

Iteration 3 is rejected unless all are true:

1. Drift detection catches synthetic drift true positives.
2. Drift detection does not flag coherent normal clusters in false-positive controls.
3. Drift detection is advisory and does not auto-split or mutate cluster assignment.
4. Singleton escalation correctly distinguishes novel/high-priority from routine singletons.
5. Singleton escalation reasoning is faithful to provided facts.
6. Recalibration proposals are generated from reviewed disposition history.
7. Split-heavy and merge-heavy histories drive directionally correct proposals.
8. Weak or conflicting histories do not produce overconfident unsafe updates.
9. Proposal values are bounded to documented safe ranges.
10. Proposal generation never changes active threshold/WINDOW.
11. Human approval is required before any parameter update.
12. Approval and rejection are audited with reviewer and timestamp.
13. Dashboard shows drift, singleton escalation, recalibration proposals, and approval state.
14. Iteration 1+2 full regression tests continue passing.
15. `pytest -q` and dependency-installed `pytest -q` both pass.
16. No live cloud dependency is required by default tests.
17. No Iteration 4 or unrelated production behavior is introduced as acceptance scope.

---

## Response to builder_plan.md

This response evaluates `team-log/builder_plan.md` strictly for Iteration 3 planning. It does not request Iteration 2 rework, Iteration 4 behavior, or implementation during planning.

### 1) Risky assumptions / missing checks in the builder plan

1. **Drift metric is underspecified.**
   - The builder plan proposes “distance of new member to centroid” or “rolling spread increase,” but does not choose the metric.
   - Risk: different implementers can pass vague tests while detecting completely different behaviors.
   - Required refinement: define the exact drift score formula, threshold, minimum cluster size, and boundary behavior before build.

2. **Drift integration hook may be too late or too local.**
   - The plan hooks drift detection after successful join in `assign_embedded_alert(...)`.
   - Risk: checking only the new alert against the current centroid can miss slow chaining drift, the known ADR-004 limitation.
   - Required refinement: tests must require evidence against founding/early members or a spread statistic, not only latest-alert-to-centroid distance.

3. **No false-positive budget for drift detection.**
   - The plan mentions false positives but does not define acceptable behavior on normal same-incident clusters.
   - Required refinement: require coherent-burst controls and assert no drift flag.

4. **Singleton novelty criteria are unspecified.**
   - The plan says classify `novel` vs `routine` but does not define deterministic baseline criteria.
   - Risk: classifier becomes subjective or test-tautological.
   - Required refinement: define a rubric using observable fields/context and require deterministic default tests.

5. **Singleton escalation must not become automatic escalation.**
   - The plan says surface escalation signal, but must explicitly forbid writing ADR-007 `escalated` disposition or external ticket handoff automatically.
   - Required refinement: assert singleton escalation is advisory until human action.

6. **Reasoning quality is mentioned but not measurable.**
   - The builder plan requires reasoning text, but not what makes it acceptable.
   - Required refinement: require faithfulness checks: cites observed facts, no hidden labels, no hallucinated context, bounded length, and classification-consistent rationale.

7. **Recalibration proposal objective is too vague.**
   - The plan says read split/merge/confirm/dismiss patterns but does not define how each action affects proposal direction.
   - Required refinement: split-heavy history should imply false merges and usually propose higher threshold/shorter WINDOW; merge-heavy history should imply false splits and usually propose lower threshold/longer WINDOW.

8. **Human approval gate needs an explicit state model.**
   - The plan says proposals are `pending_approval`, but does not define approve/reject transitions, idempotency, or audit fields.
   - Required refinement: define statuses and required metadata for approval/rejection before build.

9. **No safe bounds for proposed parameters.**
   - The builder plan acknowledges bounds are unspecified.
   - Risk: proposal may suggest invalid threshold or WINDOW.
   - Required refinement: define min/max threshold, min/max WINDOW, and clamping/rejection behavior.

10. **Review history read API needs testable semantics.**
    - The plan says add read/query methods, but not which records count as evidence.
    - Required refinement: recalibration must use reviewed disposition history only; unreviewed clusters and contradiction-only states must not alter proposals.

11. **Dashboard proposal visibility is under-specified.**
    - The plan says add proposal list and approval status.
    - Required refinement: dashboard must show current values, proposed values, evidence counts, rationale, risks, status, and approve/reject descriptors.

12. **Regression protection must include Iteration 2 security controls.**
    - The plan says run full suite but should explicitly protect suppression-before-embed, contradiction rendering, stale summary, and review queue.
    - Required refinement: add Iteration 3 integration tests that include Iteration 2 injection/suppression controls.

### 2) Drift-detection false-positive / false-negative risks

#### False-negative risks

- **Chaining drift missed by latest-centroid check**
  - A drifted cluster can absorb alerts one step at a time while each new alert remains close to the moving centroid.
  - Required assertion: detector catches a synthetic chain where final members are far from founding members.

- **Centroid-only state loses spread**
  - ADR-004 intentionally stores running centroid and count, but drift detection needs spread evidence.
  - Required assertion: implementation either tracks minimal spread/founding reference or documents/test-proves another signal that catches chain drift.

- **Small cluster under-evidence**
  - Singleton or two-alert clusters may not provide enough evidence for drift.
  - Required assertion: detector returns insufficient evidence rather than false confidence.

#### False-positive risks

- **Normal SSH log variation flagged**
  - Port changes, usernames, and minor message text changes are normal.
  - Required assertion: coherent same-incident fixture does not drift-flag.

- **Suppression/backstop/review metadata interpreted as drift**
  - Iteration 2 state fields should not affect semantic drift score.
  - Required assertion: drift score uses alert/embedding evidence, not disposition/backstop flags.

- **Closed or superseded clusters reflagged**
  - Old split/merged clusters must not re-enter active review due to drift.
  - Required assertion: closed/superseded handling is deterministic and queue-safe.

Concrete drift assertions builder plan must satisfy:
- `drift_detected == True` for synthetic chained drift.
- `drift_detected == False` for coherent control.
- Boundary behavior at threshold is documented.
- Drift detection does not mutate cluster membership/centroid/disposition.
- Drift detection does not auto-split.
- Drift result includes score, reason, and evidence.

### 3) Singleton escalation reasoning-quality and classification-proof risks

1. **Classifier can over-escalate all singletons.**
   - Required control: routine singleton fixture must not be high-priority.

2. **Classifier can miss a novel/high-risk singleton.**
   - Required control: intentionally novel singleton fixture must be flagged.

3. **Reasoning can hallucinate.**
   - Required assertions:
     - reason cites observed singleton fields or provided context,
     - reason does not mention hidden `ground_truth_incident_id`,
     - reason does not invent unavailable threat intel,
     - reason stays concise.

4. **Classification labels can be ambiguous.**
   - Required refinement: define allowed labels such as `novel`, `routine`, `high_priority`, `no_escalation`, and map them to dashboard states.

5. **Escalation signal can bypass human review.**
   - Required assertion: singleton escalation flag does not write ADR-007 `escalated` disposition and does not create external ticket automatically.

6. **Non-singletons may be processed incorrectly.**
   - Required assertion: singleton escalation runs only on `count == 1` clusters.

Concrete singleton assertions builder plan must satisfy:
- Novel singleton classified high-priority/novel with non-empty faithful reason.
- Routine singleton classified routine/no-escalation.
- No hidden labels or hallucinated context in reasoning.
- No automatic escalation disposition or ticket.
- Dashboard exposes singleton label/reason/confidence if implemented.

### 4) Recalibration proposal + human-approval-gate verification gaps

1. **Proposal generation may auto-apply.**
   - This is the highest-risk Iteration 3 failure.
   - Required assertion: active threshold/WINDOW remain unchanged immediately after proposal generation.

2. **Approval gate may be UI-only.**
   - Required assertion: service-layer approval is required before any parameter state changes.

3. **Proposal direction may be wrong.**
   - Required assertions:
     - split-heavy history produces false-merge corrective proposal,
     - merge-heavy history produces false-split corrective proposal,
     - mixed/weak evidence yields no-change or low-confidence result.

4. **Unreviewed data may contaminate recalibration.**
   - Required assertion: unreviewed clusters, unresolved contradiction states, and raw cluster guesses are excluded.

5. **Bounds may be unsafe.**
   - Required assertion: proposed threshold/WINDOW values are clamped or rejected outside safe ranges.

6. **Approval/rejection audit may be incomplete.**
   - Required fields:
     - proposal_id,
     - old threshold/WINDOW,
     - proposed threshold/WINDOW,
     - approved/rejected_by,
     - approved/rejected_at,
     - reason if rejected,
     - final status.

7. **Rejected proposals may later apply.**
   - Required assertion: rejected proposals cannot be applied without creating a new approval flow.

8. **Dashboard may imply proposed values are active.**
   - Required assertion: dashboard clearly separates current active values from pending proposal values.

Concrete recalibration assertions builder plan must satisfy:
- Proposal status is `pending_approval` after generation.
- Active parameters unchanged before approval.
- Approval requires reviewer and timestamp.
- Rejection leaves parameters unchanged.
- Approval updates only calibration state, not global constants silently.
- Audit contains old/new values and reviewer metadata.
- Proposal includes evidence counts, rationale, confidence/risk note, and bounds status.

### 5) Concrete assertions needed before build

The builder plan should be refined to require these acceptance-level assertions before implementation begins:

#### Drift detection

- Synthetic chained drift fixture is flagged.
- Coherent same-incident fixture is not flagged.
- Threshold boundary behavior is documented and tested.
- Minimum evidence guard exists.
- Drift result includes score, reason, and evidence.
- Drift is advisory only: no auto-split, no membership mutation, no disposition write.

#### Singleton escalation

- High-risk singleton fixture is classified novel/high-priority.
- Routine singleton fixture is classified routine/no-escalation.
- Classifier only runs on singleton clusters.
- Reasoning cites observed facts and no hidden ground-truth labels.
- Escalation signal does not auto-write ADR-007 escalation metadata.

#### Recalibration proposal

- Review store query API returns auditable disposition history.
- Split-heavy history produces directionally correct proposal.
- Merge-heavy history produces directionally correct proposal.
- Weak/mixed history yields no-change or low confidence.
- Proposal includes current values, proposed values, evidence counts, rationale, risks, and status.
- Proposal values respect safe bounds.
- Proposal generation does not mutate active threshold/WINDOW.

#### Human approval gate

- Pending proposal cannot affect runtime.
- Approve requires reviewer and timestamp.
- Reject requires reviewer and records status/reason.
- Approved proposal is audited with old/new values.
- Rejected proposal cannot apply.
- Dashboard shows pending/approved/rejected states clearly.

#### Regression protection

- Iteration 1 clustering/reduction tests remain passing.
- Iteration 2 suppression-before-embed remains passing.
- Iteration 2 prompt-injection contradiction rendering remains passing.
- Iteration 2 review queue/action descriptor tests remain passing.
- `pytest -q` passes.
- `python -m pip install -q -r requirements.txt && pytest -q` passes.

Until these assertions are included, the builder plan is directionally sound but not yet strict enough for adversarial Iteration 3 acceptance.
