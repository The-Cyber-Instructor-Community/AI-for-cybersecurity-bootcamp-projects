# Evaluation Round 2 — Iteration 1 Contract Review

Date: 2026-07-06  
Role: Evaluator  
Scope: Iteration 1 only  
Source of truth: `team-log/contract.md`  
Prior report reviewed: `team-log/eval_round_1.md`

## Verdict: REJECT

Round 2 shows meaningful blocker-fix progress:

- `requirements.txt` now exists and declares Streamlit.
- The direct `run_iteration1(...)` synthetic/evaluable guard bypass is fixed.
- The project now has a proper Git repository boundary at the Sift project root.
- The core Iteration 1 backend success condition works in a deterministic smoke run.

However, acceptance is still rejected because the required validation command `pytest -q` fails after installing the project’s declared dependencies. The failure is not in production pipeline behavior, but it is still a release blocker because the contract requires `pytest -q` to pass, and a reproducible declared environment must not break the test suite.

## Explicit Iteration 1 success-condition statement

The **core Iteration 1 functional success condition is met** in the non-interactive smoke test:

- 200 synthetic Wazuh-schema SSH authentication alerts are processed.
- Output contains 5 total cluster items: cluster counts `[150, 30, 18, 1, 1]`.
- Output includes 2 singletons.
- Cluster purity is `1.0`.
- Alert reduction ratio is `40.0`.
- Dashboard view model shows before/after counts: `200 -> 5`.
- Every cluster has a project-validator-valid one-sentence summary.

But **Iteration 1 is not accepted overall** because the required validation suite fails in the declared dependency environment.

---

## Evidence and command output summary

### 1) Contract and prior report

Read:
- `team-log/contract.md`
- `team-log/eval_round_1.md`

Round 1 blockers checked:
- Streamlit/dependency manifest
- core runner synthetic guard bypass
- Git/diff visibility
- golden fixture and ADR-006 test coverage
- dashboard renderability

### 2) Dependency manifest

File: `requirements.txt`

Observed:

```text
streamlit>=1.36.0
boto3>=1.34.0
pytest>=8.0.0
```

Status:
- Round 1 dependency-manifest gap is partially fixed.
- Streamlit is declared.

### 3) Full validation before installing declared requirements

Command:

```bash
pytest -q
```

Observed:

```text
.....................                                                    [100%]
21 passed in 0.06s
```

Status:
- Positive evidence, but this was before installing the declared dependency set.

### 4) Targeted validation before installing declared requirements

Command:

```bash
pytest tests/unit -q && pytest tests/integration -q && pytest tests/e2e -q
```

Observed:

```text
................                                                         [100%]
16 passed in 0.03s
...                                                                      [100%]
3 passed in 0.02s
..                                                                       [100%]
2 passed in 0.03s
```

Status:
- Unit, integration, and e2e groups pass in the pre-install environment.

### 5) Streamlit import before installing declared requirements

Command:

```bash
python - <<'PY'
try:
    import streamlit
    print({"streamlit_import": "ok", "version": getattr(streamlit, "__version__", "unknown")})
except Exception as exc:
    print({"streamlit_import": "failed", "error": type(exc).__name__, "message": str(exc)})
PY
```

Observed:

```text
{'streamlit_import': 'failed', 'error': 'ModuleNotFoundError', 'message': "No module named 'streamlit'"}
```

Status:
- Expected in an environment before dependency installation.
- Not a blocker by itself now that `requirements.txt` exists.

### 6) Installing declared requirements and verifying Streamlit

Command:

```bash
python -m pip install -q -r requirements.txt && python - <<'PY'
import streamlit
print({"streamlit_import": "ok", "version": getattr(streamlit, "__version__", "unknown")})
PY
```

Observed:

```text
{'streamlit_import': 'ok', 'version': '1.59.0'}
```

Status:
- Streamlit is installable from the declared manifest.
- Round 1 Streamlit import blocker is mostly resolved.

### 7) Full validation after installing declared requirements

Command:

```bash
pytest -q
```

Observed:

```text
.........F...........                                                    [100%]
=================================== FAILURES ===================================
________ test_dashboard_render_path_has_clear_missing_dependency_error _________

    def test_dashboard_render_path_has_clear_missing_dependency_error() -> None:
        with pytest.raises(RuntimeError, match="streamlit is required"):
>           render_dashboard(None)  # type: ignore[arg-type]
            ^^^^^^^^^^^^^^^^^^^^^^

tests/unit/test_dashboard_dependencies.py:17:
...
E       AttributeError: 'NoneType' object has no attribute 'clusters'

src/ui/dashboard.py:8: AttributeError
=========================== short test summary info ============================
FAILED tests/unit/test_dashboard_dependencies.py::test_dashboard_render_path_has_clear_missing_dependency_error
1 failed, 20 passed in 0.17s
```

Status:
- This is the remaining blocker.
- The required validation command fails in the declared dependency environment.

### 8) Direct synthetic guard bypass probe

Command:

```bash
python - <<'PY'
from datetime import datetime, timezone
from src.agents.embed_agent import DeterministicEmbeddingClient
from src.agents.summary_agent import DeterministicSummaryClient
from src.pipeline.run_iteration1 import run_iteration1
from src.pipeline.types import AlertRecord

alert = AlertRecord(
    alert_id="direct-unlabeled",
    timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
    rule_id="5710",
    rule_description="sshd authentication failed",
    full_log="sshd: Failed password for root from 10.0.0.1 port 22 ssh2",
    srcip="10.0.0.1",
    srcuser="root",
    ground_truth_incident_id=None,
)
try:
    result = run_iteration1([alert], DeterministicEmbeddingClient(), DeterministicSummaryClient())
    print({"processed": True, "raw_alert_count": result.raw_alert_count, "cluster_purity": result.cluster_purity})
except Exception as exc:
    print({"processed": False, "error": type(exc).__name__, "message": str(exc)})
PY
```

Observed:

```text
{'processed': False, 'error': 'ValueError', 'message': 'synthetic evaluation requires ground_truth_incident_id on every alert'}
```

Status:
- Round 1 synthetic guard bypass is fixed.

Code evidence:
- `src/pipeline/run_iteration1.py:65` now calls `_ensure_evaluable_synthetic(alerts)` inside the core runner.
- `tests/unit/test_synthetic_guard.py:29-45` adds direct-runner coverage.

### 9) Iteration 1 success-condition smoke

Command:

```bash
python - <<'PY'
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.pipeline.run_iteration1 import run_iteration1_from_records
from src.ui.dashboard import build_dashboard_view_model

result = run_iteration1_from_records(generate_synthetic_wazuh_ssh_alerts())
model = build_dashboard_view_model(result)
print({
    "raw_alert_count": result.raw_alert_count,
    "output_item_count": result.output_item_count,
    "singletons": len(result.singletons),
    "cluster_purity": round(result.cluster_purity, 4),
    "alert_reduction_ratio": round(result.alert_reduction_ratio, 4),
    "dashboard_before": model["before_count"],
    "dashboard_after": model["after_count"],
    "cluster_counts": [c.count for c in result.clusters],
    "summaries_present": all(c.summary for c in result.clusters),
    "one_sentence_per_cluster": all((c.summary or "").count(".") == 1 for c in result.clusters),
})
PY
```

Observed:

```text
{
  'raw_alert_count': 200,
  'output_item_count': 5,
  'singletons': 2,
  'cluster_purity': 1.0,
  'alert_reduction_ratio': 40.0,
  'dashboard_before': 200,
  'dashboard_after': 5,
  'cluster_counts': [150, 30, 18, 1, 1],
  'summaries_present': True,
  'one_sentence_per_cluster': False
}
```

Follow-up using the project’s actual sentence validator:

```bash
python - <<'PY'
from src.agents.summary_agent import one_sentence_validator
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.pipeline.run_iteration1 import run_iteration1_from_records

result = run_iteration1_from_records(generate_synthetic_wazuh_ssh_alerts())
print({
    "validator_one_sentence_per_cluster": all(one_sentence_validator(c.summary or "") for c in result.clusters),
    "summaries": [c.summary for c in result.clusters],
})
PY
```

Observed:

```text
{
  'validator_one_sentence_per_cluster': True,
  'summaries': [
    '150 SSH authentication alerts were grouped from 2026-07-01T00:00:00+00:00 to 2026-07-01T02:29:00+00:00 with source IPs 10.0.0.10.',
    '30 SSH authentication alerts were grouped from 2026-07-01T03:20:00+00:00 to 2026-07-01T03:49:00+00:00 with source IPs 10.0.0.20.',
    '18 SSH authentication alerts were grouped from 2026-07-01T08:20:00+00:00 to 2026-07-01T08:37:00+00:00 with source IPs 10.0.0.30.',
    '1 SSH authentication alerts were grouped from 2026-07-01T15:00:00+00:00 to 2026-07-01T15:00:00+00:00 with source IPs 10.0.0.40.',
    '1 SSH authentication alerts were grouped from 2026-07-01T16:20:00+00:00 to 2026-07-01T16:20:00+00:00 with source IPs 10.0.0.50.'
  ]
}
```

Status:
- Functional success condition is met.
- The naive period-count probe was invalid because timestamps/IPs contain periods; the project validator confirms one sentence per cluster.

### 10) Streamlit render smoke with real result

Command:

```bash
python - <<'PY'
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts
from src.pipeline.run_iteration1 import run_iteration1_from_records
from src.ui.dashboard import render_dashboard

try:
    result = run_iteration1_from_records(generate_synthetic_wazuh_ssh_alerts())
    render_dashboard(result)
    print({"render_dashboard_real_result": "ok"})
except Exception as exc:
    print({"render_dashboard_real_result": "failed", "error": type(exc).__name__, "message": str(exc)})
PY
```

Observed:

```text
{'render_dashboard_real_result': 'ok'}
```

There were expected Streamlit bare-mode warnings, but no exception.

Status:
- Production dashboard render path works with a real Iteration 1 result after dependencies are installed.
- The failing test is specifically a stale/invalid missing-dependency test assumption.

### 11) Git repository visibility

Command:

```bash
git rev-parse --show-toplevel
git status --short --untracked-files=all -- .
git --no-pager diff --stat -- .
git --no-pager diff --name-only -- .
```

Observed:
- Git top-level is now the project root:

```text
/Users/shegeb/the_cyber_instructor/ai_for_cybersecurity_bootcamp/capstone_projects/sift
```

- `git status --short --untracked-files=all -- .` lists project files under `src/`, `tests/`, `team-log/`, `requirements.txt`, etc.
- `git diff` remains empty because these are untracked files, not tracked modifications.

Status:
- Round 1 repository-boundary blocker is fixed.
- There is still repository hygiene risk from untracked `__pycache__` and `.DS_Store`, but this is not an Iteration 1 functional blocker.

---

## Remaining findings

### BLOCKER-1 — `pytest -q` fails after installing declared requirements

Files:
- `tests/unit/test_dashboard_dependencies.py`
- `src/ui/dashboard.py`
- `requirements.txt`

Evidence:
- `requirements.txt` installs Streamlit successfully.
- After install, `pytest -q` fails:

```text
FAILED tests/unit/test_dashboard_dependencies.py::test_dashboard_render_path_has_clear_missing_dependency_error
AttributeError: 'NoneType' object has no attribute 'clusters'
1 failed, 20 passed
```

Root cause:
- `tests/unit/test_dashboard_dependencies.py:15-17` expects `render_dashboard(None)` to raise `RuntimeError("streamlit is required")`.
- That expectation is only true when Streamlit is absent.
- Once the declared dependencies are installed, Streamlit imports successfully and `render_dashboard(None)` proceeds to `build_dashboard_view_model(None)`, causing `AttributeError`.

Why this blocks acceptance:
- `team-log/contract.md:99` requires `pytest -q` to pass.
- The reproducible declared environment must be the evaluation target.
- A test that only passes when a declared dependency is missing is not acceptable.

Required fix:
- Replace this test with one of:
  - a manifest/import test that asserts Streamlit is declared/importable after install, or
  - a monkeypatch-based missing-dependency test that simulates `ImportError` deterministically, or
  - a render smoke test using a valid `Iteration1Result`.
- Then rerun `pytest -q` after dependency installation.

---

### MAJOR-1 — Golden pipeline test still uses weak output assertions

Files:
- `tests/integration/test_iteration1_pipeline.py`
- `src/pipeline/synthetic.py`

Evidence:
- The smoke test proves exact output is currently `[150, 30, 18, 1, 1]` with 5 output items and 2 singletons.
- But `tests/integration/test_iteration1_pipeline.py:20-24` still asserts only:
  - `result.raw_alert_count == 200`
  - `result.output_item_count >= 5`
  - `result.alert_reduction_ratio > 1.0`
  - `result.cluster_purity > 0.9`
  - summary calls equal clusters

Why this matters:
- The deterministic generator documents 3 major incidents + 2 singletons.
- The test would pass with extra output clusters, as long as output count remains `>= 5` and purity stays above `0.9`.
- This is not a blocker because the smoke proves the current implementation meets the success condition, but the regression test is not strict enough.

Required fix:
- Assert:
  - `result.output_item_count == 5`
  - `len(result.singletons) == 2`
  - `[c.count for c in result.clusters] == [150, 30, 18, 1, 1]`
  - expected source IPs and time spans.

---

### MAJOR-2 — ADR-006 test coverage remains under-adversarial

Files:
- `tests/unit/test_summary_input_shape.py`
- `src/logic/cluster_close.py`

Evidence:
- `tests/unit/test_summary_input_shape.py:47-58` checks field types for clusters of size 1, 3, and 150.
- It does not assert exact schema fields, exact first/last/outlier samples, two-alert fallback, or no variable-length alert array leakage.
- `src/logic/cluster_close.py:17-38` does build a fixed `SummaryInput`, so implementation appears mostly aligned, but the test would miss several ADR-006 regressions.

Why this matters:
- ADR-006 is one of the core contract behaviors.
- Current implementation likely satisfies the broad contract, but tests are not strict enough to prove all details.

Required fix:
- Add exact-schema assertions using the `SummaryInput` dataclass fields.
- Add a 2-alert cluster fallback test.
- Add explicit aggregation tests for one/two/more-than-two source IPs and usernames.
- Add a sample-selection test for first, last, and intended outlier behavior.

---

### MINOR-1 — Summary live-output validation remains advisory risk

Files:
- `src/agents/summary_agent.py`
- `src/logic/cluster_close.py`

Evidence:
- `one_sentence_validator(...)` exists in `src/agents/summary_agent.py:66-73`.
- Deterministic summaries pass the validator.
- Live Bedrock output is not validated before assignment to `cluster.summary`.

Why this matters:
- The contract requires one LLM sentence per cluster.
- The deterministic test path passes, but live Claude could return multiple sentences unless checked.

Why not a blocker:
- Iteration 1 deterministic tests and smoke path are sufficient for demo/eval.
- Live Bedrock execution is behind an adapter seam and not required for default CI.

Required fix:
- Wrap summary assignment with validator enforcement or adapter-level normalization/rejection.
- Add a bad-summary stub test.

---

### MINOR-2 — Repository hygiene: generated files are untracked

Files:
- `.DS_Store`
- `src/**/__pycache__`
- `tests/**/__pycache__`

Evidence:
- `git status --short --untracked-files=all -- .` lists `.DS_Store` and many `__pycache__` files.

Why this matters:
- Not an Iteration 1 functional issue, but it increases review noise.
- These should be ignored before staging/committing.

Required fix:
- Add `.gitignore` entries for `.DS_Store`, `__pycache__/`, and `*.pyc`.

---

## Resolved round-1 findings

| Round 1 finding | Round 2 status | Evidence |
|---|---:|---|
| Missing Streamlit/dependency manifest | PARTIAL | `requirements.txt` exists and installs Streamlit; however test suite fails after install |
| Synthetic guard bypass through core runner | RESOLVED | direct probe now raises `ValueError`; `run_iteration1.py:65`; test added |
| Git repository boundary unreliable | RESOLVED | `git rev-parse --show-toplevel` now returns project root |
| Dashboard render not runnable | RESOLVED FOR REAL RESULT | after installing requirements, `render_dashboard(result)` returns ok with bare-mode warnings |
| Golden pipeline weak assertions | STILL MAJOR | test still uses `>= 5`, not exact deterministic fixture shape |
| ADR-006 weak assertions | STILL MAJOR | tests still type-check more than behavior-check |
| Live one-sentence validation | STILL MINOR | deterministic validator passes; live output not enforced |

---

## Contract checklist coverage status

| Contract item | Status | Evidence |
|---|---:|---|
| 200 synthetic Wazuh-schema SSH auth alerts in | PASS | smoke: `raw_alert_count: 200`; generator used |
| Clusters out with count | PASS | smoke cluster counts `[150, 30, 18, 1, 1]`; dashboard rows include count |
| Clusters out with time span | PASS | dashboard view model includes `time_span_seconds` |
| Clusters out with source IP | PASS | dashboard rows include `source_ip`; summaries include IP |
| One LLM sentence per cluster | PASS | project validator returned `True` for every cluster |
| Dashboard before/after count visible | PASS | view model `dashboard_before: 200`, `dashboard_after: 5`; Streamlit render smoke ok after install |
| Embedding adapter and Titan model path | PASS | previously verified; no regression observed |
| `rule.description + full_log` embedding contract | PASS | tests pass |
| ADR-003 pre-filter before similarity | PASS | targeted tests pass |
| ADR-003 boundary behavior | PASS | targeted tests pass |
| ADR-004 centroid update | PASS | targeted tests pass |
| ADR-006 fixed payload implementation | PASS/PARTIAL | implementation uses fixed dataclass; tests remain weak |
| Synthetic-only guard | PASS | direct core-runner probe now rejects unlabeled input |
| Streamlit dependency declared | PASS | `requirements.txt` includes Streamlit |
| Streamlit dependency install/import | PASS | post-install import ok: version `1.59.0` |
| `pytest -q` | FAIL | fails after installing declared requirements |
| Iteration 1 scope only | PASS | no Iteration 2/3 behavior observed |

---

## Residual risks

1. **Validation fragility**
   - A test currently passes only when Streamlit is absent and fails when declared dependencies are installed.
   - This is the only remaining blocker.

2. **Golden regression weakness**
   - Current behavior meets the demo target, but tests do not lock exact expected output.

3. **ADR-006 proof gap**
   - Fixed-size payload exists, but tests are not adversarial enough to catch schema/sample-selection drift.

4. **Live LLM output risk**
   - One-sentence contract is validated for deterministic summaries but not enforced on live Claude output.

5. **Repository hygiene**
   - Untracked cache/system files should be ignored before staging.

---

## Required changes before acceptance

1. Fix `tests/unit/test_dashboard_dependencies.py` so `pytest -q` passes after `pip install -r requirements.txt`.
2. Rerun:
   - `python -m pip install -q -r requirements.txt`
   - `pytest -q`
3. Preferably strengthen, but not necessarily block on:
   - exact golden fixture assertions
   - ADR-006 exact schema/sample tests
   - live summary one-sentence enforcement
   - `.gitignore` cleanup

Until the post-install `pytest -q` failure is fixed, Round 2 remains **REJECT**.
