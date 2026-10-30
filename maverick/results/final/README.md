# Final results (Kaggle, qwen2.5 7B and 14B)

These are the results reported in the capstone report.

| File | What it is |
|---|---|
| `REPORT.md` | Every metric for every run: missed attacks, workload, F1/F2, ROC-AUC, calibration, red team, investigation scores |
| `metrics.json` | The same numbers in machine-readable form |
| `REPORT_heldout.md`, `metrics_heldout.json` | The main run on a held-out dataset (different seed), never used for tuning |
| `sample_cases/` | Case files for INC-0006 (prompt injection), INC-0029 (invented fact), INC-0062 (leading question) and INC-0088 (decoy) |

Running the lab yourself writes new results to `results/`, which git ignores.
