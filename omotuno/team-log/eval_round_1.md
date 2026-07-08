# Evaluation Round 1 — Iteration 1 Contract Review

Date: 2026-07-06  
Role: Evaluator  
Scope: Iteration 1 only  
Source of truth: `team-log/contract.md`

## Verdict: REJECT

The implementation shows meaningful Iteration 1 progress and the default pytest suite passes, but it is not contract-complete under strict evaluation.

Primary rejection reasons:

1. The Streamlit dashboard target is not actually runnable in the current project environment: `streamlit` is not installed and no dependency manifest exists.
2. The core `run_iteration1(...)` entrypoint can process unlabeled/non-evaluable `AlertRecord` objects directly, bypassing the synthetic-only evaluation guard enforced by wrapper functions.
3. Git diff/status evidence is unreliable for evaluating the requested “unstaged changes”: project-scoped `git diff` is empty even though implementation files exist, and `git rev-parse --show-toplevel` reports `/Users/shegeb`, not this project directory.

The passing tests are high-signal, but these blockers mean the implementation cannot be accepted as verifiable and demo-ready.

---

## Evidence from commands/tests

### Contract read

Read `team-log/contract.md`.

Relevant contract requirements:
- Success condition: 200 synthetic Wazuh-schema SSH auth alerts in; clusters out with count, time span, source IP, and one LLM sentence per cluster; dashboard shows before/after count.
- Streamlit is the dashboard target.
- Synthetic-only data is mandatory for demo/eval.
- Required final command: `pytest -q` passes.
- Deterministic tests with adapter seams are required.

### Git/diff inspection

Command:

```bash
git status --short && printf '\n--- DIFF STAT ---\n' && git --no-pager diff --stat && printf '\n--- CHANGED FILES ---\n' && git --no-pager diff --name-only
```

Observed:

```text
--- DIFF STAT ---

--- CHANGED FILES ---
```

Command:

```bash
git status --short --untracked-files=all -- . && printf '\n--- DIFF STAT PATHSCOPED ---\n' && git --no-pager diff --stat -- . && printf '\n--- DIFF NAME-ONLY PATHSCOPED ---\n' && git --no-pager diff --name-only -- .
```

Observed:

```text
--- DIFF STAT PATHSCOPED ---

--- DIFF NAME-ONLY PATHSCOPED ---
```

Additional evidence:

```bash
git rev-parse --show-toplevel
```

Observed:

```text
/Users/shegeb
```

Risk: the implementation files exist under the project directory, but `git diff` and project-scoped status do not expose them as unstaged changes. This makes normal code-review evidence incomplete.

### File tree / test collection

Command:

```bash
pwd && ls -la && git ls-files && pytest --collect-only -q
```

Observed:
- Current directory: `/Users/shegeb/the_cyber_instructor/ai_for_cybersecurity_bootcamp/capstone_projects/sift`
- `src/` and `tests/` directories exist.
- `git ls-files` returned no tracked files in the displayed output.
- Pytest collected 18 tests:
  - 13 unit tests
  - 3 integration tests
  - 2 e2e tests

### Full validation

Command:

```bash
pytest -q
```

Observed:

```text
..................                                                       [100%]
18 passed in 0.07s
```

### Targeted grouped validation

Command:

```bash
pytest tests/unit -q && pytest tests/integration -q && pytest tests/e2e -q
```

Observed:

```text
.............                                                            [100%]
13 passed in 0.20s
...                                                                      [100%]
3 passed in 0.03s
..                                                                       [100%]
2 passed in 0.03s
```

### Non-interactive pipeline smoke

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
  'summaries_present': True
}
```

This is strong positive evidence for the core backend/demo path.

### Synthetic guard bypass probe

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
{'processed': True, 'raw_alert_count': 1, 'cluster_purity': 0.0}
```

This is a blocker because the lower-level orchestration function can process unlabeled evaluation input, despite the contract requiring synthetic-only demo/eval data.

### Streamlit/dashboard dependency probe

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

Dependency manifest probes:
- `requirements*.txt`: no files found.
- `pyproject.toml`: no file found.

This is a blocker because `team-log/contract.md` explicitly says Streamlit is the dashboard target.

---

## Findings

### BLOCKER-1 — Streamlit dashboard target is not runnable in current project environment

Files:
- `src/ui/dashboard.py`
- missing dependency manifest: no `requirements*.txt`, no `pyproject.toml`

Evidence:
- `src/ui/dashboard.py:30-41` implements `render_dashboard(...)` using Streamlit.
- Streamlit import probe failed with `ModuleNotFoundError: No module named 'streamlit'`.
- No dependency manifest exists to install Streamlit.

Why this blocks acceptance:
- `team-log/contract.md:28` says Streamlit is the dashboard target.
- `team-log/contract.md:38` requires a Streamlit dashboard showing before/after counts and cluster outputs.
- The e2e tests only validate `build_dashboard_view_model(...)`; they do not prove `render_dashboard(...)` is runnable.

Required fix:
- Add a project dependency manifest that includes Streamlit, or otherwise provide a reproducible install command.
- Add a lightweight smoke check that imports Streamlit or validates the dashboard command path in an environment with declared dependencies.

---

### BLOCKER-2 — Synthetic-only evaluation guard can be bypassed through the core runner

Files:
- `src/pipeline/run_iteration1.py`
- `src/pipeline/types.py`
- `tests/unit/test_synthetic_guard.py`

Evidence:
- `src/pipeline/run_iteration1.py:110-127` enforces `ground_truth_incident_id` only in `run_iteration1_from_records(...)`.
- `src/pipeline/run_iteration1.py:130-139` enforces it only in `run_iteration1_from_json(...)`.
- `src/pipeline/run_iteration1.py:56-107` does not enforce synthetic/evaluable input on direct `AlertRecord` input.
- Direct probe showed `run_iteration1([unlabeled_alert], ...)` processed successfully and returned `cluster_purity: 0.0`.
- `tests/unit/test_synthetic_guard.py:17-21` covers only `run_iteration1_from_records(...)`, not the core runner.

Why this blocks acceptance:
- `team-log/contract.md:27` says synthetic-only data is mandatory for demo/eval.
- `team-log/contract.md:53` requires `ground_truth_incident_id` for purity checks.
- `team-log/contract.md:79` requires non-synthetic or unlabeled eval input to fail or be marked non-evaluable.
- A public/core orchestration path silently processes unlabeled input, which can hide broken evaluation and purity reporting.

Required fix:
- Either enforce evaluable synthetic input in `run_iteration1(...)`, or explicitly split API semantics so the direct runner cannot be used for demo/eval without a required `require_synthetic_eval` guard.
- Add a targeted test that direct orchestration rejects or marks unlabeled input non-evaluable.

---

### BLOCKER-3 — Requested unstaged-change review cannot be trusted from git diff/status evidence

Files:
- Repository metadata / review process issue
- Affects all implementation files under `src/` and `tests/`

Evidence:
- `git diff --stat` and `git diff --name-only` returned empty output.
- Path-scoped `git status --short --untracked-files=all -- .` also returned no changed files.
- `git rev-parse --show-toplevel` returned `/Users/shegeb`, not the project root.
- `git ls-files` output was empty in the project inspection command, despite implementation files being present under `src/` and `tests/`.

Why this blocks acceptance:
- The task explicitly required inspection of current unstaged changes (`git diff`) and relevant new files.
- The relevant files exist, but they are not represented in normal `git diff` evidence.
- This prevents a reliable diff-based review of what changed and increases risk that files are ignored/untracked outside the intended repository boundary.

Required fix:
- Put the project in a proper repository boundary or update git tracking/ignore configuration so `src/`, `tests/`, `team-log/contract.md`, and related files appear in normal project-scoped status/diff.
- Re-run evaluation with a meaningful diff/status.

---

### MAJOR-1 — Golden pipeline test accepts weak output expectations

Files:
- `tests/integration/test_iteration1_pipeline.py`
- `src/pipeline/synthetic.py`

Evidence:
- `src/pipeline/synthetic.py:7-11` documents exactly 200 alerts, 3 major incidents, and 2 singletons.
- `tests/integration/test_iteration1_pipeline.py:20-24` asserts:
  - `raw_alert_count == 200`
  - `output_item_count >= 5`
  - `alert_reduction_ratio > 1.0`
  - `cluster_purity > 0.9`
  - summary calls equal cluster count
- The same test does not assert the documented exact expected shape:
  - `output_item_count == 5`
  - cluster counts `[150, 30, 18, 1, 1]`
  - exactly 2 singletons
  - exact expected source IPs/time spans

Why this matters:
- The smoke run produced the desired shape, but the test would still pass with extra spurious clusters as long as `output_item_count >= 5` and purity stayed above 0.9.
- The contract success condition is measurable; tests should lock the golden fixture shape.

Required fix:
- Strengthen the golden integration test to assert exact expected output for the deterministic fixture.

---

### MAJOR-2 — ADR-006 fixed-shape test does not prove the exact schema or outlier semantics

Files:
- `src/logic/cluster_close.py`
- `tests/unit/test_summary_input_shape.py`

Evidence:
- `src/logic/cluster_close.py:17-38` builds `SummaryInput`.
- `tests/unit/test_summary_input_shape.py:47-58` checks fields are present and typed for 1, 3, and 150 alert clusters.
- It does not assert:
  - exact field set
  - exactly first, last, and farthest-from-centroid sample logs for clusters with 3+ alerts
  - more-than-two source IP/user behavior is numeric count and not omitted
  - no variable-length alert arrays can reach the summary client

Why this matters:
- ADR-006 is a core Iteration 1 contract.
- The production code appears to use a fixed dataclass, which is good, but the tests are not adversarial enough to catch schema drift or incorrect outlier selection.

Required fix:
- Add assertions for exact `SummaryInput` fields and expected sample values.
- Add tests for one/two/more-than-two IP/user aggregation behavior.
- Add an explicit negative/spy assertion that full member arrays are not passed to the summary adapter.

---

### MAJOR-3 — Farthest-from-centroid sample uses proxy embeddings, not actual member vectors

Files:
- `src/logic/cluster_close.py`
- `src/logic/clustering.py`
- `src/pipeline/types.py`

Evidence:
- `src/logic/cluster_close.py:21-23` selects outlier using `cosine_similarity(cluster.centroid, _embed_proxy(a))`.
- `_embed_proxy(...)` is defined at `src/logic/cluster_close.py:41-54`.
- `ClusterState` in `src/pipeline/types.py:31-43` stores members but not member vectors.

Why this matters:
- ADR-006 requires first, last, and farthest-from-centroid sample log lines.
- A proxy vector derived from text is not necessarily the same embedding space as the cluster centroid, especially if live Titan embeddings are used.
- This may pick the wrong outlier in live or mixed-adapter scenarios.

Counterpoint:
- ADR-004 says no raw vectors are stored beyond centroid/count.
- Therefore, exact outlier selection conflicts with the current storage-minimization decision unless another deterministic strategy is defined.

Required fix:
- Document and test the chosen Iteration 1 compromise, or store only the minimal extra information needed to identify farthest-from-centroid at assignment time without retaining all raw vectors.
- Add an ADR-006 test that verifies the intended outlier-selection behavior.

---

### MINOR-1 — Dashboard e2e validates view model, not Streamlit rendering

Files:
- `tests/e2e/test_dashboard_iteration1.py`
- `src/ui/dashboard.py`

Evidence:
- `tests/e2e/test_dashboard_iteration1.py:11-42` uses `build_dashboard_view_model(...)`.
- It does not call `render_dashboard(...)`.
- Streamlit is not importable in the environment.

Why this matters:
- This overlaps with BLOCKER-1, but even after adding dependencies, dashboard tests should distinguish backend view-model correctness from UI renderability.

Required fix:
- Keep the view-model tests, but add a dashboard import/render smoke test once dependencies are declared.

---

### MINOR-2 — Summary one-sentence validation is not enforced on live Bedrock output

Files:
- `src/agents/summary_agent.py`
- `src/pipeline/run_iteration1.py`

Evidence:
- `src/agents/summary_agent.py:66-73` defines `one_sentence_validator(...)`.
- `run_iteration1(...)` closes clusters by assigning `cluster.summary = summary_builder(payload)` via `close_eligible_clusters(...)`.
- No production path validates or rejects multi-sentence live model output before dashboard display.

Why this matters:
- The contract requires one LLM sentence per cluster.
- Tests validate deterministic summaries, but live model output can violate the sentence constraint.

Required fix:
- Add output validation around summary generation or make the summary adapter contract enforce one sentence.
- Add a unit test with a bad summary stub returning multiple sentences.

---

## Contract checklist coverage status

| Contract item | Status | Evidence / notes |
|---|---:|---|
| Minimal project skeleton and typed contracts | PASS | `src/pipeline/types.py`, `src/pipeline/run_iteration1.py`, module structure present |
| Synthetic Wazuh SSH ingestion with schema validation | PASS | `src/pipeline/ingest.py:19-63`; tests pass |
| Deterministic 200-alert fixture/generator | PASS | `src/pipeline/synthetic.py:6-63`; smoke shows 200 |
| `ground_truth_incident_id` for purity | PARTIAL | Generator includes labels; wrappers enforce; direct `run_iteration1(...)` bypass processes unlabeled input |
| Embedding adapter seam and Bedrock Titan path | PASS | `src/agents/embed_agent.py:15-90`; model ID in `src/pipeline/config.py:3` |
| Embed text from `rule.description + full_log` | PASS | `src/agents/embed_agent.py:11-12`; dedicated test collected |
| ADR-003 time-window eligibility | PASS | `src/logic/clustering.py:56-60`; boundary tests pass |
| ADR-003 pre-filter before similarity | PASS | `SimilaritySpy` path in `src/logic/clustering.py:21-27,64-67`; targeted test passes |
| Cosine similarity assignment | PASS | `src/logic/clustering.py:12-18,72-89` |
| `last_seen` updates on join | PASS | `src/logic/clustering.py:80`; targeted test passes |
| ADR-004 incremental centroid update | PASS | `src/logic/clustering.py:73-79`; centroid tests pass |
| Centroid renormalization conditional | PASS | Configurable `renormalize_centroid`; targeted test passed |
| Minimal cluster state for outputs/dashboard | PASS | `ClusterState` fields in `src/pipeline/types.py:31-43` |
| Cluster-close logic with batch replay semantics | PASS | `run_iteration1.py:77-93`; no wall-clock use observed |
| Summary adapter seam and close-trigger path | PASS | `src/agents/summary_agent.py`; `close_eligible_clusters(...)` |
| ADR-006 fixed-size payload | PARTIAL | Dataclass is fixed-size, but tests do not fully assert exact schema/outlier behavior |
| Fallback for 1-/2-alert clusters | PASS | `src/logic/cluster_close.py:23-26`; tested for 1 alert, not explicitly 2 |
| One summary sentence per cluster | PARTIAL | Deterministic path passes; live output is not validated before display |
| Streamlit dashboard target | FAIL | `src/ui/dashboard.py` imports Streamlit, but dependency missing and no manifest exists |
| Dashboard before count | PASS | smoke: `dashboard_before: 200`; e2e test passes |
| Dashboard after count | PASS | smoke: `dashboard_after: 5`; e2e test passes |
| Dashboard reduction metric | PASS | e2e test checks model value |
| Dashboard per-cluster fields | PARTIAL | view-model fields tested; Streamlit render not runnable |
| Iteration 1 scoped only | PASS | No suppression, review queue, prompt-injection backstop, stale cache, or Iteration 3 agent observed |
| `pytest -q` passes | PASS | 18 passed |
| Lint/format/type checks | NOT CONFIGURED | No `pyproject.toml` or requirements manifest found |
| Local demo run command | PARTIAL | Python smoke works; no declared CLI/dependency setup command validated |

---

## Residual risks

1. **Repository boundary/tracking risk**
   - The project appears inside a broader Git repository rooted at `/Users/shegeb`.
   - Normal diff/status did not show the implementation files.
   - This can hide review-relevant changes and makes handoff risky.

2. **No dependency manifest**
   - Streamlit, boto3, pytest, and any lint/type tooling are not declared locally.
   - A fresh environment may not reproduce the passing tests or dashboard.

3. **Live Bedrock behavior is untested**
   - Adapter seams exist, which is correct for deterministic tests.
   - However, live Titan/Claude payload compatibility is not validated by any optional env-gated smoke test.

4. **Summary faithfulness is deterministic-stub-only**
   - There is no production backstop in Iteration 1, which is acceptable because prompt-injection defense is Iteration 2.
   - Still, the one-sentence and facts-only constraints can be violated by live Claude output unless validated.

5. **Golden fixture is generated in code, not persisted as a fixture artifact**
   - The contract permits deterministic generator artifact, so this is acceptable.
   - But generated fixture expectations should be locked more tightly in tests.

---

## Required changes before re-evaluation

1. Add a dependency manifest or reproducible setup path that includes Streamlit.
2. Add a dashboard smoke test or command proving the Streamlit dashboard target can run/import.
3. Close the synthetic guard bypass by enforcing or clearly separating evaluable synthetic mode in `run_iteration1(...)`.
4. Strengthen the golden pipeline test to assert exact deterministic fixture output:
   - 200 input alerts
   - 5 output items
   - 2 singletons
   - cluster counts `[150, 30, 18, 1, 1]`
   - expected source IPs/time spans
5. Strengthen ADR-006 tests for exact schema, 2-alert fallback, distinct-value aggregation, and outlier behavior.
6. Make git status/diff evidence reliable for this project before requesting acceptance review again.

Until those are addressed, Iteration 1 remains rejected despite the passing default test suite.
