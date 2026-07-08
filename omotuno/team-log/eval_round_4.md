# Evaluation Round 4 — Iteration 2 Final Adversarial Report

Date: 2026-07-06  
Role: Evaluator  
Scope: Iteration 2 only  
Source of truth: `team-log/contract.md`

## Verdict: REJECT

The Iteration 2 implementation satisfies the three explicit demo success conditions in deterministic tests/probes, and both required validation commands pass. However, the implementation is rejected against the full contract because the default SQLite persistence paths for suppression/review stores are broken (`unable to open database file`). Suppression rule persistence is explicitly in scope for Iteration 2, so the implementation is not contract-complete.

A second major issue was also found: failed Dismiss-with-suppression validation mutates the cluster to `dismissed` before raising, leaving inconsistent review state after a failed action.

---

## Required command evidence

### Full test suite

Command:

```bash
pytest -q
```

Result:

```text
.......................................                                  [100%]
39 passed in 0.15s
```

### Declared dependency validation

Command:

```bash
python -m pip install -q -r requirements.txt && pytest -q
```

Result:

```text
.......................................                                  [100%]
39 passed in 0.13s
```

These are strong positive signals: the deterministic suite passes both before and after dependency installation.

---

## Explicit Iteration 2 success-condition confirmation

### 1) Review queue visible — PASS

Evidence:
- `src/ui/dashboard.py:41-54` builds `review_queue` and `unreviewed_count`.
- `tests/e2e/test_dashboard_iteration2.py:23-39` asserts:
  - `review_queue` exists,
  - `unreviewed_count` exists,
  - queue count matches queue length,
  - rows include contradiction/stale/disposition/raw facts/action descriptors,
  - action descriptors include all five actions.

Additional probe output:

```text
{'review_queue_visible': True, 'unreviewed_count': 5, ...}
```

Status: **PASS**.

### 2) Crafted injection payload shows contradiction detected instead of trusted LLM sentence — PASS

Evidence:
- `tests/integration/test_injection_pipeline.py:25-46` injects adversarial text into a synthetic SSH log line and uses a poisoned summary client.
- The test asserts contradiction clusters exist and have:
  - `summary == "contradiction detected"`,
  - `summary_status == "contradiction_detected"`,
  - non-empty `backstop_reasons`.

Additional dashboard probe output:

```text
{
  'contradiction_rows': 5,
  'queue_contradictions': 5,
  'trusted_poisoned_text_visible': False,
  'contradiction_summaries': ['contradiction detected', 'contradiction detected', 'contradiction detected'],
  'raw_facts_present': True
}
```

Status: **PASS**.

### 3) All five analyst actions write correct metadata — PASS for success path

Evidence:
- `src/logic/review_gate.py` implements:
  - Confirm: `confirm_cluster(...)`
  - Dismiss: `dismiss_cluster(...)`
  - Escalate: `escalate_cluster(...)`
  - Split: `split_cluster(...)`
  - Merge: `merge_clusters(...)`
- `tests/unit/test_review_actions.py` covers all five.
- `tests/integration/test_review_lifecycle.py` applies all five and asserts dispositions/audit entries.

Additional probe output:

```text
{
  'confirm': {'disposition': 'confirmed', 'reviewed_by': 'analyst@example.com', 'reviewed_at': '2026-07-01T00:00:00+00:00'},
  'dismiss': {'disposition': 'dismissed', 'reviewed_by': 'analyst@example.com', 'reviewed_at': '2026-07-01T00:00:00+00:00', 'rule_created': True},
  'escalate': {'disposition': 'escalated', 'reviewed_by': 'analyst@example.com', 'reviewed_at': '2026-07-01T00:00:00+00:00', 'escalation_ref': 'TICKET-1'},
  'split': {'disposition': 'split', 'reviewed_by': 'analyst@example.com', 'reviewed_at': '2026-07-01T00:00:00+00:00', 'superseded_reason': 'split', 'new_counts': [2, 2]},
  'merge': {'input_dispositions': ['merged', 'merged'], 'input_reviewed_by': ['analyst@example.com', 'analyst@example.com'], 'merged_count': 4},
  'review_actions': ['confirm', 'dismiss', 'escalate', 'split', 'merge']
}
```

Status: **PASS for valid actions**, with a major failure on invalid Dismiss behavior noted below.

---

## Findings by severity

### BLOCKER-1 — SQLite suppression/review persistence paths are broken

Files:
- `src/pipeline/config.py`
- `src/store/suppression_store.py`
- `src/store/review_store.py`
- `src/pipeline/run_iteration2.py`

Contract requirement:
- `team-log/contract.md:24`: suppression rule persistence keyed by `(rule_id, srcip)` with expiry and volume override.
- `team-log/contract.md:65`: add suppression store.
- `team-log/contract.md:88`: persist audit metadata for all actions.

Evidence:
- `src/pipeline/config.py:10-11` sets:
  - `SUPPRESSION_DB_PATH = "data/sift_suppression.sqlite"`
  - `REVIEW_DB_PATH = "data/sift_review.sqlite"`
- The `data/` directory does not exist.
- SQLite constructors do not create parent directories.

Probe command result:

```text
{'suppression': 'failed', 'path': 'data/sift_suppression.sqlite', 'error': 'OperationalError', 'message': 'unable to open database file'}
{'review': 'failed', 'path': 'data/sift_review.sqlite', 'error': 'OperationalError', 'message': 'unable to open database file'}
```

Iteration 2 runner probe:

```text
{'run_iteration2_sqlite': 'failed', 'error': 'OperationalError', 'message': 'unable to open database file'}
```

Why this blocks acceptance:
- Persistence is in scope, not optional.
- The default configured persistence path fails immediately.
- The passing suite primarily exercises in-memory stores and therefore misses the broken persistence path.

Required fix:
- Ensure parent directory creation before opening SQLite DBs, or change default paths to an existing location.
- Add tests for default `SQLiteSuppressionStore(SUPPRESSION_DB_PATH)` and `SQLiteReviewStore(REVIEW_DB_PATH)`.
- Add a test for `run_iteration2_from_records(..., use_sqlite_suppression=True)`.

---

### MAJOR-1 — Failed Dismiss-with-suppression mutates cluster metadata before raising

Files:
- `src/logic/review_gate.py`
- `tests/unit/test_review_actions.py`

Evidence:
- `dismiss_cluster(...)` calls `_mark_reviewed(cluster, "dismissed", ...)` before validating suppression expiry and store requirements.
- Probe for missing suppression expiry:

```text
{
  'raised': 'ValueError',
  'message': 'suppression expiry is required when create_suppression=True',
  'post_failure_disposition': 'dismissed',
  'post_failure_reviewed_by': 'analyst@example.com'
}
```

Why this matters:
- A failed action leaves the cluster marked as dismissed even though the requested Dismiss-with-suppression action was rejected.
- This can remove an item from review queue or create false audit/disposition state.
- Contract requires action metadata correctness; failed actions should be atomic or explicitly documented as partial, which would be unsafe here.

Required fix:
- Validate all Dismiss preconditions before mutating cluster state.
- Add a test that failed Dismiss leaves disposition/review metadata unchanged.
- Apply the same atomicity review to Escalate/Split/Merge invalid paths.

---

### MAJOR-2 — Review queue implementation diverges between `build_review_queue` and dashboard view model for superseded clusters

Files:
- `src/logic/review_gate.py`
- `src/ui/dashboard.py`

Evidence:
- `src/logic/review_gate.py:240-245` excludes superseded clusters:
  - `c.superseded_by is None and (...)`
- `src/ui/dashboard.py:41-45` rebuilds review queue from rows using only:
  - `row["disposition"] is None or row["contradiction_detected"]`
- The dashboard row does not include `superseded_by`, so dashboard cannot apply the same supersession filtering.

Why this matters:
- Split/merge originals should remain auditable but should not appear as active unresolved review items.
- Divergent queue logic can cause dashboard review queue to disagree with pipeline `result.review_queue`.

Required fix:
- Include supersession fields in dashboard rows and apply the same queue predicate as `build_review_queue`, or build dashboard queue from `result.review_queue`.
- Add an e2e test where split/merge originals do not appear as active queue rows.

---

### MINOR-1 — Backstop numeric parser is simplistic

Files:
- `src/logic/backstop.py`

Evidence:
- `backstop_check_summary(...)` checks the first integer in the candidate summary as the reported count.

Risk:
- If a summary starts with a timestamp/year before the count, backstop may misclassify count.
- Current deterministic summaries begin with count, so default tests pass.

Required hardening:
- Parse count using a stricter pattern or require a fixed summary schema.
- Add tests where timestamps precede the alert count.

---

### MINOR-2 — Generated cache/system files remain noisy in status

Evidence:
- `git status` output includes `__pycache__` files and other generated artifacts.

Risk:
- Review noise and accidental staging.

Required hygiene:
- Add `.gitignore` entries for `__pycache__/`, `*.pyc`, `.DS_Store`, and local SQLite DB files.

---

## Positive coverage notes

The implementation has strong coverage for the main Iteration 2 behavior:

- Suppression-before-embed:
  - `src/pipeline/run_iteration2.py:53-64`
  - `tests/unit/test_suppression_before_embed.py`
  - `tests/integration/test_iteration2_pipeline.py`

- Suppression keying/expiry/3x boundary:
  - `src/logic/suppression.py:24-45`
  - `tests/unit/test_suppression_store.py`

- Structural tagging:
  - `src/agents/summary_agent.py:9-27`
  - `tests/unit/test_prompt_injection_defense.py`

- Backstop:
  - `src/logic/backstop.py`
  - `tests/unit/test_backstop.py`
  - `tests/integration/test_injection_pipeline.py`

- Stale summary behavior:
  - `src/logic/clustering.py:86-90`
  - `src/logic/cluster_close.py:90-101`
  - `tests/unit/test_summary_cache_stale.py`
  - `tests/integration/test_stale_summary_cache.py`

- Review actions:
  - `src/logic/review_gate.py`
  - `tests/unit/test_review_actions.py`
  - `tests/integration/test_review_lifecycle.py`

- Dashboard review queue/state:
  - `src/ui/dashboard.py`
  - `tests/e2e/test_dashboard_iteration2.py`

---

## Final assessment

The implementation passes the deterministic suite and satisfies the three explicit user-facing success conditions. It is close.

However, because Iteration 2 explicitly includes suppression/review persistence and the configured SQLite persistence path fails, the implementation is **REJECTED** until that blocker is fixed. The Dismiss atomicity issue should also be addressed before re-evaluation because failed review actions must not leave incorrect disposition metadata behind.
