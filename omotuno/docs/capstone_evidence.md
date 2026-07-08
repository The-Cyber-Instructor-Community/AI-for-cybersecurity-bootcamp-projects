# Sift Requirements Traceability Audit
Date: 2026-07-07
Scope: Full repo audit against Sift capstone requirements and ADR-001..ADR-008.

## TL;DR
- Iteration 1: Implemented and tested
- Iteration 2: Implemented and tested
- Iteration 3: Implemented and tested
- ADR-001..ADR-008: Implemented with explicit code evidence
- Remaining known scope limits are documented (synthetic SSH-focused capstone scope)

## Iteration Goal Traceability

### Iteration 1 (embed, cluster, summarize)
Status: MET  
Evidence:
- Pipeline orchestration: `src/pipeline/run_iteration1.py`
- Embedding shape (ADR-001): `src/agents/embed_agent.py`
- Time-window + cosine assignment: `src/logic/clustering.py`, `src/logic/time_window.py`
- Centroid updates (ADR-004): `src/logic/centroid.py`
- Close-trigger summaries: `src/logic/cluster_close.py`
- Validation tests: `tests/integration/test_iteration1_pipeline.py`, `tests/e2e/test_dashboard_iteration1.py`

### Iteration 2 (review gate, suppression, injection defense, stale cache)
Status: MET  
Evidence:
- Pipeline: `src/pipeline/run_iteration2.py`
- Review gate/actions (ADR-007): `src/logic/review_gate.py`
- Suppression-before-embed: `src/logic/suppression.py`
- Injection/backstop defenses (ADR-008): `src/agents/summary_agent.py`, `src/logic/backstop.py`
- Stale summary behavior: `src/logic/clustering.py`, `src/logic/cluster_close.py`
- Deterministic adversarial fixture: `src/pipeline/synthetic.py::generate_adversarial_wazuh_ssh_alerts`
- Validation tests: `tests/integration/test_iteration2_pipeline.py`, `tests/integration/test_injection_pipeline.py`, `tests/e2e/test_dashboard_iteration2.py`

### Iteration 3 (drift, singleton escalation, recalibration with human approval)
Status: MET  
Evidence:
- Pipeline: `src/pipeline/run_iteration3.py`
- Drift agent: `src/logic/drift_agent.py`
- Singleton escalation agent: `src/logic/singleton_escalation_agent.py`
- Recalibration proposal + approval gate: `src/logic/recalibration_agent.py`, `src/pipeline/run_iteration3.py`
- Review audit persistence: `src/store/review_store.py`
- Validation tests: `tests/unit/test_drift_agent.py`, `tests/unit/test_singleton_escalation_agent.py`, `tests/unit/test_recalibration_agent.py`, `tests/integration/test_iteration3_pipeline.py`, `tests/e2e/test_dashboard_iteration3.py`

## ADR Traceability

- ADR-001 Embedding input fields  
  - `src/agents/embed_agent.py::build_embedding_text`
- ADR-002 Cluster assignment threshold rule  
  - `src/logic/clustering.py::assign_embedded_alert`
- ADR-003 Time-window pre-filter and batch replay semantics support  
  - `src/logic/time_window.py`, `src/logic/clustering.py`, `src/logic/cluster_close.py`
- ADR-004 Incremental centroid update  
  - `src/logic/centroid.py::update_centroid_incremental`
- ADR-005 Summary trigger + stale/on-demand regeneration path  
  - `src/logic/cluster_close.py`, `src/logic/review_gate.py::open_cluster_for_review`
- ADR-006 Fixed-size summary input  
  - `src/logic/cluster_close.py::build_summary_input`, `src/agents/summary_agent.py`
- ADR-007 Analyst actions and review lifecycle  
  - `src/logic/review_gate.py`, `src/store/review_store.py`
- ADR-008 Prompt injection mitigation layers  
  - Structural tagging: `src/agents/summary_agent.py`
  - Deterministic backstop denylist/fact checks: `src/logic/backstop.py`
  - Contradiction handling in pipeline: `src/logic/cluster_close.py`

## Gap/Risk Remediation Completed

1. Vector store choice risk  
   - Added explicit backend seam and selector (`in_memory`, `faiss`, `chroma`)  
   - Files: `src/store/cluster_store.py`, `src/pipeline/config.py`, `src/pipeline/run_iteration1.py`
   - Parity + invalid backend tests: `tests/integration/test_iteration1_pipeline.py`

2. Deterministic injection-catch evidence risk  
   - Added deterministic adversarial synthetic fixture
   - File: `src/pipeline/synthetic.py`
   - Integration coverage uses fixture: `tests/integration/test_injection_pipeline.py`

3. Auditability/source-of-truth risk  
   - Added this traceability audit artifact
   - Added repository requirement source file: `Sift_Capstone_Requirements.md`

## Validation (latest run)
- Unit tests: pass
- Integration tests: pass
- E2E tests: pass

## Notes
This capstone remains intentionally scoped to synthetic Wazuh-schema SSH alerts and local execution paths, per the documented project scope.
