# Eval Rubric

How to score a pipeline run. Run each brief in `sample-ideas/` through the
orchestrator, then score the generated `THREAT_MODEL.md` against this rubric. The
refund agent (`scripts/sample_findings.json`) is the fourth fixture.

## Part A — Shift-left coverage (core, 10 pts)

Each of the five questions the system must answer, scored 0–2:
`0` = not addressed · `1` = partially / no basis · `2` = fully answered with basis.

| # | Question | 2 pts requires |
|---|----------|----------------|
| Q1 | Assets inventoried | all five asset classes named or explicit N/A, plus system-specific assets |
| Q2 | Untrusted entry points tagged as data | every entry point listed with a data-tagged verdict; FAIL is a valid, correct answer |
| Q3 | ASTRIDE per asset, worst case | findings span the relevant categories; worst case stated |
| Q4 | Tool calls least-privilege | each tool assessed for scoped / short-lived / caller-bound |
| Q5 | ASR baseline pre + continuous | baseline addressed; GAP is correct when none exists yet |

## Part B — Quality (differentiation, 8 pts)

| Dimension | 0–2 | 2 pts requires |
|-----------|-----|----------------|
| Grounding / traceability | | every finding tagged with ASTRIDE **and** an OWASP LLM ID |
| Routing correctness | | each finding lands in the right defense layer (L1–L4) |
| Residual-risk reasoning | | recommendations note what the control does *not* cover |
| Determinism | | report was produced by `render_report.py` (a `report_findings.json` exists, severities match the matrix) |

**Total: /18.** A strong capstone run scores 15+.

## Part C — Per-brief should-catch

Each brief's `## Should-catch` list is its answer key. Count how many the run
surfaced. Missing an obvious one (e.g., the multi-agent cross-layer cascade, or the
coding agent's supply-chain risk) is the clearest signal of a weak run — more
telling than the point total.

## Part D — Self-check: signs of a weak output

- Intake gate didn't fire (jumped to threats without asking blocking questions)
- Findings with no OWASP/ASTRIDE tag — reads as guessed, not grounded
- Every finding routed to one layer (usually L3) — routing table too blunt
- Severity labels with no ASR basis shown
- Report is freeform prose, no `report_findings.json` — renderer was skipped
- Q2/Q5 marked PASS when they should be FAIL/GAP — over-optimistic verdict
- MAESTRO layers shown as L-numbers colliding with defense L1–L4 (renderer should reject this)

## How to record results

For each of the four systems, note: score /18, should-catch count, and any miss.
Four rows is enough evidence for the writeup that the tool works across system
types, not just the one it was built on.
