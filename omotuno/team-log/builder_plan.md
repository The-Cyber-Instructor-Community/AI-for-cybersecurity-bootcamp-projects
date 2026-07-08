# Builder Plan — Iteration 3 (Planning Only: Drift + Singleton Escalation + Recalibration Proposal)

Date: 2026-07-07  
POC: Builder (Iteration 3 Planning)  
Scope: **Iteration 3 only** (no Iteration 2 rework, no Iteration 4 features, no implementation in this step)

TL;DR: Add a dedicated Iteration 3 orchestration layer on top of existing Iteration 2 flows with minimal blast radius:  
1) drift detection agent for intra-cluster spread changes,  
2) singleton escalation agent for novel vs routine singletons with reasoning,  
3) threshold/window recalibration proposal agent using disposition history, with **human approval required** and no auto-apply path.

---

## 0) Source-of-truth note

Requested file `Sift_Capstone_Requirements.md` is not present in this repository path.  
Planning basis used:
- User-provided Iteration 3 scope and success conditions (this task prompt),
- existing architecture in `src/...`,
- `team-log/contract.md` (which explicitly listed Iteration 3 items as out-of-scope for Iteration 2).

---

## 1) Current relevant architecture/files

### Pipeline/orchestration
- `src/pipeline/run_iteration2.py`
  - Current deterministic/live client selection, suppression-before-embed, clustering, close-trigger summary, backstop, review queue assembly.
  - Best base to preserve as stable and compose Iteration 3 from a **new** runner (`run_iteration3.py`) rather than mutating Iteration 2 behavior.

### State/types
- `src/pipeline/types.py`
  - `ClusterState` already contains Iteration 2 review/backstop/stale fields.
  - `Iteration2Result` includes clusters/singletons/review_queue and counters.
  - Natural insertion point for Iteration 3 typed state additions and `Iteration3Result`.

### Clustering and close lifecycle
- `src/logic/clustering.py`
  - `assign_embedded_alert` updates centroid/members and stale-summary flags.
  - This is the right seam for collecting spread/drift features with minimal overhead.
- `src/logic/cluster_close.py`
  - `close_eligible_clusters` finalizes clusters and summary state.
  - Natural seam to evaluate singleton escalation when singletons are closed/finalized.

### Review/disposition history
- `src/store/review_store.py`
  - Currently supports logging actions (`log_action`) to in-memory/SQLite, but no read/query API yet.
  - Recalibration agent needs read/query methods over historical dispositions (e.g., split/merge/dismiss/escalate frequencies).

### Dashboard/view model
- `src/ui/dashboard.py`
  - Emits cluster rows, review queue, and Iteration 2 indicators.
  - Should be extended with optional Iteration 3 panels/fields (drift flags, singleton reasoning, recalibration proposals pending approval) without breaking existing keys.

### Existing test shape
- Unit/integration/e2e suite structure already established under `tests/`.
- Iteration 3 should add targeted tests and preserve Iteration 2 regressions with full suite execution.

---

## 2) Ordered Iteration 3 implementation tasks (file-level)

> Design principle: keep Iteration 2 stable, add Iteration 3 via additive modules + dedicated entrypoint.

### Task 1 — Extend typed contracts for Iteration 3 signals and proposals
**Files**
- `src/pipeline/types.py` (modify)

**Planned additions**
- `ClusterState` additive fields (exact names to finalize during implementation):
  - drift: `drift_flag: bool`, `drift_score: float`, `drift_reason: str | None`
  - singleton escalation: `singleton_escalated: bool`, `singleton_reasoning: str | None`, `singleton_label: str | None` (`novel` | `routine`)
- New proposal DTOs:
  - `RecalibrationProposal` with proposed `similarity_threshold`, proposed `window`, rationale, confidence/summary stats, created_at, status (`pending_approval`, `approved`, `rejected`)
- New result type:
  - `Iteration3Result` extending Iteration 2 outputs with:
    - `drifted_clusters`
    - `singleton_escalations`
    - `recalibration_proposals`

**Why first**
- Keeps downstream callsites typed and deterministic before adding logic.

---

### Task 2 — Add Drift Detection Agent module
**Files**
- `src/logic/drift_agent.py` (new)
- `src/logic/clustering.py` (minimal modify for callsite hook)
- `src/pipeline/config.py` (optional minimal constants only if needed)

**Planned behavior**
- Compute/track intra-cluster spread metric (e.g., distance of new member to centroid, rolling spread increase).
- Flag cluster as drifted when score exceeds deterministic threshold.
- Persist drift score/reason to cluster state.
- No auto-remediation; output is a flag for analyst visibility and later policy decisions.

**Minimal integration point**
- After successful join in `assign_embedded_alert(...)`.

---

### Task 3 — Add Singleton Escalation Agent module
**Files**
- `src/logic/singleton_escalation_agent.py` (new)
- `src/logic/cluster_close.py` (minimal modify)
- `src/agents/summary_agent.py` (only if a small reasoning client seam is needed; deterministic default required)

**Planned behavior**
- Evaluate singleton clusters (`count == 1`) at close/finalization.
- Classify as `novel` vs `routine` and attach explicit reasoning text (deterministic in default test mode).
- Surface escalation signal for analyst queue/workflow.

**Minimal integration point**
- In `close_eligible_clusters(...)` when `should_close` and cluster is singleton.

---

### Task 4 — Add Recalibration Proposal Agent (human-approval only)
**Files**
- `src/logic/recalibration_agent.py` (new)
- `src/store/review_store.py` (modify: add read/query API over audit history)
- `src/pipeline/run_iteration3.py` (new)
- `src/pipeline/config.py` (optional guardrails/bounds constants)

**Planned behavior**
- Read disposition history (e.g., split/merge/confirm/dismiss patterns).
- Produce proposal(s) for updated `SIMILARITY_THRESHOLD` and/or `WINDOW`.
- Mark all proposals as `pending_approval`.
- Explicitly **never auto-apply** to live runtime params.
- Include rationale summary and evidence counts to support analyst decision.

**Minimal integration point**
- End of Iteration 3 run, after base Iteration 2 outputs computed.

---

### Task 5 — Add dedicated Iteration 3 runner
**Files**
- `src/pipeline/run_iteration3.py` (new)
- `src/pipeline/run_iteration2.py` (no behavioral changes; optional tiny import-safe refactor only if required)

**Planned flow**
1. Execute Iteration 2-compatible pipeline steps
2. Evaluate drift flags during clustering lifecycle
3. Evaluate singleton escalation at close/finalization
4. Generate recalibration proposal from review history
5. Return `Iteration3Result` with proposal status `pending_approval`

**Why**
- Preserves Iteration 2 regression safety and limits blast radius.

---

### Task 6 — Dashboard/view model visibility for Iteration 3 outputs
**Files**
- `src/ui/dashboard.py` (modify, additive fields only)

**Planned additions**
- Cluster rows include drift fields and singleton escalation fields.
- Payload includes recalibration proposal list and approval status.
- Keep existing Iteration 2 keys intact for backward compatibility.

---

### Task 7 — Test plan implementation (Iteration 3 coverage + regression)
**Files (new)**
- `tests/unit/test_drift_agent.py`
- `tests/unit/test_singleton_escalation_agent.py`
- `tests/unit/test_recalibration_agent.py`
- `tests/integration/test_iteration3_pipeline.py`
- `tests/e2e/test_dashboard_iteration3.py`

**Planned assertions for required success conditions**
- Synthetically drifted cluster is flagged.
- Novel singleton is escalated with reasoning.
- Recalibration proposal generated and status is pending human approval (not auto-applied).

---

## 3) ADR/requirements traceability

Because `Sift_Capstone_Requirements.md` is unavailable in the repo, traceability is mapped to:
1) user-specified Iteration 3 scope/success criteria in this task,
2) prior contract boundary in `team-log/contract.md` (Iteration 3 items listed as next scope).

| Iteration 3 requirement | Planned components/files |
|---|---|
| Drift detection agent monitoring intra-cluster spread and flagging drifted clusters | `src/logic/drift_agent.py`, callsite in `src/logic/clustering.py`, fields in `src/pipeline/types.py`, visibility in `src/ui/dashboard.py` |
| Singleton escalation agent classifying novel vs routine with reasoning | `src/logic/singleton_escalation_agent.py`, callsite in `src/logic/cluster_close.py`, fields in `src/pipeline/types.py`, visibility in `src/ui/dashboard.py` |
| Threshold/window recalibration proposal from disposition history, human approval only | `src/logic/recalibration_agent.py`, read APIs in `src/store/review_store.py`, orchestration in `src/pipeline/run_iteration3.py`, proposal DTOs in `src/pipeline/types.py`, dashboard proposal visibility |

Success condition mapping:
- Drifted cluster flagged → unit + integration drift tests
- Novel singleton escalated with reasoning → unit + integration singleton tests
- Recalibration proposal generated and held for human approval → unit + integration recalibration tests with explicit pending status and no parameter mutation

---

## 4) Risks / compatibility concerns

1. **Iteration 2 regression risk**
   - Mitigation: add `run_iteration3.py` instead of modifying Iteration 2 behavior in-place.

2. **False positives in drift detection**
   - Mitigation: deterministic metric + threshold bounds + synthetic adversarial tests.

3. **Singleton classifier overfitting to synthetic patterns**
   - Mitigation: explicit reasoning output and deterministic rules first; no hidden autonomous action.

4. **Recalibration proposal becoming implicit auto-tuning**
   - Mitigation: enforce proposal-only contract (`pending_approval`) and no runtime config mutation path.

5. **Review history retrieval from store**
   - Mitigation: additive read/query methods in `review_store` without altering existing logging semantics.

6. **Dashboard contract drift**
   - Mitigation: additive keys only; preserve existing Iteration 2 payload keys and tests.

---

## 5) Open questions / blockers (only truly unspecified)

1. **Missing requirements file path**
   - `Sift_Capstone_Requirements.md` not found in repository.
   - Needed: confirm canonical requirements artifact/path for final wording/traceability.

2. **Drift threshold definition**
   - Exact thresholding policy for “drifted cluster” not specified (absolute score vs delta-over-baseline).
   - Needed: choose default deterministic threshold policy.

3. **Singleton novelty criteria**
   - Precise rule/model criteria for `novel` vs `routine` is unspecified.
   - Needed: deterministic baseline rubric for Iteration 3 acceptance tests.

4. **Recalibration objective and bounds**
   - Which objective dominates (e.g., split/merge corrective ratio, purity proxy, queue pressure) and acceptable proposal bounds are unspecified.
   - Needed: explicit objective priorities + min/max bounds for proposed threshold/window.

No other blockers identified for planning.

---

## 6) Validation command proposal (for future implementation phase)

### Targeted unit tests
```bash
pytest -q tests/unit/test_drift_agent.py
pytest -q tests/unit/test_singleton_escalation_agent.py
pytest -q tests/unit/test_recalibration_agent.py
```

### Integration tests
```bash
pytest -q tests/integration/test_iteration3_pipeline.py
```

### E2E/dashboard tests
```bash
pytest -q tests/e2e/test_dashboard_iteration3.py
```

### Full regression suite
```bash
pytest -q
python -m pip install -q -r requirements.txt && pytest -q
```

### Minimal synthetic acceptance probes (post-implementation)
```bash
python - <<'PY'
from src.pipeline.run_iteration3 import run_iteration3_from_records
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts

result = run_iteration3_from_records(generate_synthetic_wazuh_ssh_alerts())
print({
    "drifted_clusters": len(result.drifted_clusters),
    "singleton_escalations": len(result.singleton_escalations),
    "proposal_statuses": [p.status for p in result.recalibration_proposals],
})
PY
```

Expected acceptance shape:
- drifted_clusters >= 1 on drift-injected synthetic scenario,
- at least one singleton marked `novel` with non-empty reasoning on novelty scenario,
- at least one recalibration proposal with `status == "pending_approval"` and no auto-apply side effects.

## Response to test_plan.md

### 1) Feasibility of proposed tests (Iteration 3 only)

Overall feasibility is high, with good alignment to Iteration 3 outcomes and safety constraints.  
The unit matrix is comprehensive and appropriate for adversarial validation, especially:
- drift true-positive/false-positive/boundary/evidence sufficiency controls,
- singleton escalation correctness plus reasoning quality checks,
- proposal generation directionality + approval-gate invariants.

Implementation practicality notes:
- The full plan is broad; execution should be phased to avoid overbuilding:
  1. deterministic unit seams first (drift/singleton/recalibration core logic),
  2. integration over real pipeline/store paths,
  3. dashboard/e2e visibility and approval-flow behavior.
- Several tests assume proposal application mechanics; those are feasible if scoped to a small “active calibration state” seam, not a broad config rewrite.

### 2) Exact deterministic seams/adapters required

To satisfy Iteration 3 tests while keeping default CI offline and deterministic:

1. **Drift detector seam**
   - Pure function/service, e.g. `evaluate_cluster_drift(cluster, config) -> DriftResult`.
   - Inputs: cluster members/centroid/count and optional prior spread baseline.
   - Output: deterministic `drift_detected`, `drift_score`, `reason_codes`, `evidence`.

2. **Singleton escalation seam**
   - Pure function/service, e.g. `classify_singleton(cluster, context) -> SingletonEscalationResult`.
   - Default deterministic rubric/stub; no mandatory live model in `pytest -q`.
   - Output: label (`novel`/`routine`), priority/escalate flag, bounded reasoning, confidence (if used).

3. **Recalibration proposal seam**
   - Pure proposal generator, e.g. `propose_calibration(history, current_params, bounds) -> ProposalResult`.
   - Consumes reviewed dispositions only; returns pending proposal/no-op with rationale/evidence.
   - Never mutates active params directly.

4. **Review history read seam**
   - Add query methods to review store (in-memory + SQLite parity), e.g.:
     - `list_actions(...)`
     - `summarize_dispositions(...)`
   - Keep existing `log_action` behavior unchanged.

5. **Approval gate seam**
   - Explicit transition API, e.g. `approve_proposal(...)`, `reject_proposal(...)`.
   - Requires reviewer identity, writes timestamps/audit, enforces idempotency/terminal states.
   - Separate from proposal generation to prevent accidental auto-apply.

6. **Active calibration state seam (minimal)**
   - Small source of active threshold/window values for runner reads.
   - Proposal creation does not alter this state; approval transition is the only write path.

7. **Dashboard view-model seam (existing)**
   - Continue validating pure dict output (not Streamlit interaction).
   - Additive Iteration 3 fields only: drift indicators, singleton reasoning, proposal/approval status.

### 3) Minimal implementation strategy to satisfy tests without overbuilding

- Keep `run_iteration2.py` stable; add a dedicated `run_iteration3.py` orchestrator.
- Implement three focused logic modules only:
  - `drift_agent.py`
  - `singleton_escalation_agent.py`
  - `recalibration_agent.py`
- Add minimal typed DTO/state fields in `types.py` to carry outputs; avoid large schema rewrites.
- Extend `review_store.py` with read/query capability (additive only), not a new storage system.
- Add a compact approval-state path for proposals (pending/approved/rejected) and audit metadata.
- Make all Iteration 3 behavior advisory by default:
  - no autonomous split/merge/remediation,
  - no automatic threshold/window updates.
- Implement dashboard updates as additive view-model keys to preserve Iteration 2 compatibility.
- Prioritize deterministic tests and keep optional live-model checks env-gated.

### 4) Requirement-interpretation mismatches needing contract clarification

1. **Drift threshold semantics**
   - Need explicit rule for boundary behavior (`== threshold` flag or no-flag) and float tolerance.

2. **Drift evidence baseline**
   - Clarify whether drift compares against founding members, rolling baseline, or both (test plan implies chained-drift sensitivity).

3. **Singleton “novel” rubric**
   - Need explicit deterministic features/weights for novel vs routine to avoid subjective/hallucination-prone outcomes.

4. **Proposal direction policy**
   - Test plan assumes split-heavy => stricter clustering and merge-heavy => looser clustering; confirm this is normative contract behavior.

5. **Active parameter source**
   - Clarify whether approved values update in-memory runtime only, persisted store state, or both.

6. **Approval API semantics**
   - Clarify idempotency and terminal behavior (re-approve/reject after decision) to avoid ambiguous tests.

7. **Reviewed-only history definition**
   - Confirm which action records count as “reviewed dispositions” for recalibration evidence (e.g., include escalate/dismiss weights or split/merge only).
