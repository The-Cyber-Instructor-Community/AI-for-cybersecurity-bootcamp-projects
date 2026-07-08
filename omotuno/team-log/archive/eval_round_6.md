# Evaluation Round 6 — Iteration 3 Final Adversarial Report

Date: 2026-07-07  
Role: Evaluator  
Scope: Iteration 3 only  
Source of truth: `team-log/contract.md`

## Verdict: REJECT

The Iteration 3 implementation passes the full test suite and satisfies two of the three explicit success conditions in direct probes. However, it is rejected because adversarial checks found contract-significant issues:

1. Drift detection flags all three normal coherent ground-truth clusters as drifted, failing the required false-positive control.
2. Singleton escalation scoring uses `ground_truth_incident_id` / hidden synthetic labels as a novelty signal, violating the reasoning/classification requirement that singleton decisions be based on observable inputs/context only.

These issues mean the implementation is not reliable enough to accept even though `pytest` passes.

---

## Required command evidence

### Full test suite

Command:

```bash
pytest -q
```

Result:

```text
....................................................                     [100%]
52 passed in 0.25s
```

### Declared dependency validation

Command:

```bash
python -m pip install -q -r requirements.txt && pytest -q
```

Result:

```text
....................................................                     [100%]
52 passed in 0.91s
```

The required commands pass.

---

## Explicit Iteration 3 success-condition verification

### 1) Synthetically drifted cluster flagged — PARTIAL / NOT SUFFICIENT

Positive evidence:
- `tests/integration/test_iteration3_pipeline.py:30-33` asserts at least one drifted cluster exists.
- Smoke probe on the default synthetic fixture returned:

```text
{'drifted_count': 3, ...}
```

Adversarial concern:
- The flagged clusters are not a specifically drift-injected fixture; they are the normal default synthetic clusters.
- A false-positive control probe showed all coherent ground-truth clusters are flagged:

```text
[
  {'cluster_id': 'cluster-1', 'count': 150, 'ground_truth_ids': ['inc-a'], 'drift_detected': True, 'drift_score': 0.6042, 'reason': 'centroid_drift'},
  {'cluster_id': 'cluster-2', 'count': 30, 'ground_truth_ids': ['inc-b'], 'drift_detected': True, 'drift_score': 0.748, 'reason': 'centroid_drift'},
  {'cluster_id': 'cluster-3', 'count': 18, 'ground_truth_ids': ['inc-c'], 'drift_detected': True, 'drift_score': 0.8188, 'reason': 'centroid_drift'}
]
```

Status: **REJECT** for drift behavior. True-positive existence is not enough when false-positive controls fail.

### 2) Novel singleton escalated with reasoning — PASS, with major caveat

Positive evidence:
- Smoke probe returned one novel singleton escalation:

```text
{
  'singleton_escalations': 1,
  'singleton_details': [
    ('cluster-4', 'routine', False, 'authentication failure pattern present; isolated singleton incident context'),
    ('cluster-5', 'novel', True, 'privileged user=oracle; authentication failure pattern present; uncommon source ip=10.0.0.50; isolated singleton incident context')
  ]
}
```

- Probe confirmed no automatic ADR-007 escalation metadata is written:

```text
[
  {'cluster_id': 'cluster-4', 'label': 'routine', 'escalated_signal': False, 'disposition': None, 'escalation_ref': None},
  {'cluster_id': 'cluster-5', 'label': 'novel', 'escalated_signal': True, 'disposition': None, 'escalation_ref': None}
]
```

Status: **PASS for visible novel singleton escalation**, but see MAJOR-1: hidden-label influence.

### 3) Recalibration proposal generated and held pending human approval — PASS

Evidence:
- Probe with split-heavy reviewed history:

```text
{
  'before': (0.82, 12),
  'after': (0.82, 12),
  'proposal_status': 'pending_approval',
  'current': (0.82, 12),
  'proposed': (0.85, 10),
  'active_in_result': (0.82, 12)
}
```

This confirms:
- proposal generated,
- status is `pending_approval`,
- proposed values differ,
- active threshold/window do not auto-apply.

Status: **PASS**.

---

## Findings by severity

### BLOCKER-1 — Drift detector fails false-positive control on normal coherent clusters

Files:
- `src/logic/drift_agent.py`
- `tests/unit/test_drift_agent.py`
- `tests/integration/test_iteration3_pipeline.py`

Contract requirements:
- `team-log/contract.md:10`: drift detection monitors intra-cluster spread and flags drifted clusters.
- `team-log/contract.md:46`: drift advisory-only and meaningful.
- `team-log/contract.md:108-110`: requires true-positive, false-positive control, threshold boundary and minimum-evidence tests.

Evidence:
- Default synthetic clusters are ground-truth pure:
  - cluster-1: `inc-a`
  - cluster-2: `inc-b`
  - cluster-3: `inc-c`
- All three are flagged as drifted by `evaluate_cluster_drift(...)`:

```text
cluster-1 inc-a -> drift_detected True
cluster-2 inc-b -> drift_detected True
cluster-3 inc-c -> drift_detected True
```

Why this blocks acceptance:
- A detector that flags every normal high-count cluster does not distinguish drift from ordinary SSH brute-force variation.
- The success condition “synthetically drifted cluster is flagged” is not adversarially proven if normal clusters are also flagged.
- This increases analyst review noise and undermines the claimed Iteration 3 value.

Root cause risk:
- `src/logic/drift_agent.py` computes proxy vectors from text and compares them to the cluster centroid, but the proxy vectors may not be in the same embedding space as the centroid.
- The resulting score appears calibrated to flag normal clusters.

Required fix:
- Add an explicit coherent-cluster false-positive fixture and require `drift_detected == False`.
- Add a true drift-injected fixture separate from normal default synthetic clusters.
- Recalibrate or change the drift metric so it catches true drift without flagging pure normal clusters.
- Ensure drift evidence compares semantically meaningful vectors or a documented proxy with validated controls.

---

### MAJOR-1 — Singleton escalation uses hidden ground-truth labels as a scoring feature

Files:
- `src/logic/singleton_escalation_agent.py`
- `tests/unit/test_singleton_escalation_agent.py`

Contract requirements:
- `team-log/contract.md:11`: classify novel singletons vs routine noise with reasoning.
- `team-log/contract.md:47`: deterministic rubric with reasoning from observed fields/context only.
- `team-log/contract.md:112`: reasoning faithfulness tests with no hidden-label facts.

Evidence:
- `src/logic/singleton_escalation_agent.py:39-41` increases novelty score if:
  - `ground_truth_incident_id is None`, or
  - `"singleton"` appears in `ground_truth_incident_id`.

Adversarial probe with identical observable fields and only different hidden ground truth:

```text
{'incident_id': 'inc-a', 'score': 0.2, 'reasoning': 'authentication failure pattern present'}
{'incident_id': 'inc-singleton-hidden', 'score': 0.4, 'reasoning': 'authentication failure pattern present; isolated singleton incident context'}
```

Why this matters:
- `ground_truth_incident_id` is an evaluation label, not an analyst-observable runtime feature.
- Using it makes the classifier partly label-leaky and can inflate test performance.
- The reasoning “isolated singleton incident context” is derived from hidden label state, not observable alert/context fields.

Required fix:
- Remove `ground_truth_incident_id` from singleton escalation scoring and reasoning.
- Base singleton escalation only on observable alert metadata, cluster count, source IP/user/rule patterns, historical context, or review history.
- Add a test where two identical alerts differing only in `ground_truth_incident_id` receive identical singleton scores/reasoning.

---

### MAJOR-2 — Drift true-positive test is not clearly separated from normal default fixture

Files:
- `tests/integration/test_iteration3_pipeline.py`
- `tests/unit/test_drift_agent.py`

Evidence:
- `tests/integration/test_iteration3_pipeline.py:32` asserts only `len(result.drifted_clusters) >= 1`.
- Given the false-positive probe, this assertion can pass even when normal clusters are incorrectly flagged.
- `tests/unit/test_drift_agent.py` checks threshold behavior but does not include a realistic coherent false-positive control.

Why this matters:
- The test proves the detector flags something, not that it flags actual drift.

Required fix:
- Add two integration fixtures:
  1. normal coherent fixture expected `0` drift flags,
  2. drift-injected fixture expected `>=1` drift flag.
- Assert exact expected drift IDs where possible.

---

### MINOR-1 — Recalibration approval uses mutable module-global state by default

Files:
- `src/pipeline/run_iteration3.py`

Evidence:
- `run_iteration3.py:20-23` defines `_ACTIVE_CALIBRATION_STATE`.
- `approve_recalibration_proposal(...)` mutates that state if no explicit state is passed.

Risk:
- Tests or long-running sessions can leak calibration state across calls if they use defaults.
- Current probes with explicit state prove no auto-apply at proposal time, but default global mutation should be handled carefully.

Required hardening:
- Prefer explicit calibration state injection in tests and runner calls.
- Add reset or isolated state fixture.
- Ensure proposal generation never mutates the global state.

---

## Positive coverage notes

The implementation includes useful Iteration 3 coverage and architecture:

- Dedicated Iteration 3 runner:
  - `src/pipeline/run_iteration3.py`

- Drift agent:
  - `src/logic/drift_agent.py`
  - minimum evidence and threshold boundary logic exist.

- Singleton escalation:
  - `src/logic/singleton_escalation_agent.py`
  - labels and reasoning are surfaced.

- Recalibration:
  - `src/logic/recalibration_agent.py`
  - proposal status defaults to `pending_approval`.
  - split-heavy and merge-heavy directions are tested.
  - approval and rejection APIs exist.

- Dashboard:
  - `src/ui/dashboard.py` exposes drift, singleton, proposal fields and proposal action descriptors.

- Review store:
  - `src/store/review_store.py` has read/query methods for reviewed dispositions.

- Regression:
  - Full suite includes Iteration 1+2 tests and passes.

---

## Final assessment

Iteration 3 is **rejected** despite passing tests because the adversarial checks show that the drift detector fails false-positive control and singleton escalation uses hidden evaluation labels.

To accept Iteration 3, fix the drift false-positive behavior and remove hidden-label dependency from singleton escalation, then add tests that prove:
- normal coherent clusters are not drift-flagged,
- drift-injected clusters are drift-flagged,
- singleton scoring/reasoning is invariant to `ground_truth_incident_id`,
- recalibration remains pending/no-auto-apply.
