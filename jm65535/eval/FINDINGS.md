# Evaluation findings — triage decision quality

Durable write-up of the model comparison. (The raw table in
`eval/model_comparison.md` is regenerated on every run; this file holds the
interpretation.)

## Setup — what was measured, and why it's fair

- **Task:** single-shot triage verdict — `malicious` / `ambiguous` / `benign` —
  given the playbook + already-collected enrichment findings.
- **Held-out set:** 86 cases (80 generated with seed 7 + 6 analyst-exception cases
  with seed 11), disjoint from both the RAG corpus and the LoRA training data. The
  seeds are fixed, so **every arm sees identical inputs** and the numbers are
  directly comparable across runs.
- **Fair isolation:** every arm uses the same prompt format, and the same RAG
  context when RAG is on. We compare **security judgment, not tool-use** — an 8B
  won't reliably drive the multi-tool agentic loop, so tool-use is validated
  separately on Claude in the live pipeline. Grading it here would measure the
  wrong thing and unfairly bury the small models.
- **Metrics:** `accuracy` (3-way exact match), `malicious_f1` (precision + recall
  on the threat class), `over_trigger_rate` (non-malicious cases wrongly escalated
  — the false-alarm / alert-fatigue rate, lower is better), `avg_latency` (s/case).
- **Ground-truth mix:** malicious 39, ambiguous 33, benign 14.

## Results (n = 86)

| arm | accuracy | malicious_f1 | over_trigger_rate | avg_latency |
|---|---|---|---|---|
| Claude | 0.651 | 0.733 | 0.383 | 2.89 |
| Claude + RAG | **0.802** | **0.857** | 0.191 | 3.08 |
| Foundation-Sec | 0.756 | 0.853 | 0.085 | 7.56 |
| Foundation-Sec + RAG | 0.709 | 0.831 | 0.128 | 11.0 |
| Foundation-Sec-LoRA | 0.674 | 0.727 | **0.064** | 6.53 |
| Foundation-Sec-LoRA + RAG | 0.663 | 0.754 | 0.085 | 9.72 |

- **Claude** = frontier model (`claude-sonnet-5`), Anthropic API, $/case.
- **Foundation-Sec** = `Foundation-Sec-8B-Instruct`, open, security-specialized 8B,
  on-prem via Ollama at **$0/case, air-gapped**.
- **Foundation-Sec-LoRA** = the same 8B after LoRA fine-tuning on ~500 judgment
  cases (4-bit base, MLX), served via `mlx_lm.server`.

## Findings

**1. RAG is the highest-ROI component.** It lifted the frontier model **+15pts
accuracy** (0.651 → 0.802) and roughly halved its over-triggering (0.383 → 0.191),
for zero training. Retrieving the analyst's prior judgments is the cheapest,
biggest win in the whole system.

**2. A security-specialized open 8B is the on-prem sweet spot out of the box.**
Stock Foundation-Sec essentially ties Claude+RAG on malicious-detection F1
(0.853 vs 0.857) with **less than half the false-alarm rate** (0.085 vs 0.191) —
at $0/case, air-gapped, and no fine-tuning. It gives up some 3-way accuracy
(0.756 vs 0.802), mostly on the low-stakes ambiguous-vs-benign call.

**3. Small-data fine-tuning did NOT beat retrieval or the stock base — it slightly
degraded capability.** LoRA dropped accuracy 8pts (0.756 → 0.674) and F1 13pts
(0.853 → 0.727) versus the stock model. Its *only* improvement — the lowest
over-trigger of any arm (0.064) — came from becoming **trigger-shy**: it labels
more things not-malicious, which cuts false alarms but also misses real threats
(hence the lower recall/F1). On a SOC task that is a net regression, since a missed
detection is worse than an extra false positive. RAG on top of LoRA changed nothing
(0.674 → 0.663).

*Why:* ~500 synthetic examples plus a light LoRA can't add to an 8B already
pretrained on a large security corpus — they only perturb strong priors, nudging
the decision boundary toward "benign." This is the textbook small-data
fine-tuning outcome.

## Recommendation

- **On-prem / privacy / cost-sensitive → stock Foundation-Sec.** Nearly Claude+RAG's
  threat-detection quality, fewest false alarms, $0, air-gapped, no training.
- **Peak accuracy, API cost acceptable → Claude + RAG.**
- **Skip fine-tuning for a corpus this size.** Spend the effort growing the labeled
  set (which helps RAG immediately), not on a LoRA that, at best, matches retrieval.
- **RAG is the value-add regardless of base model** — build the judgment corpus.

## Caveats

- **n = 86** is a solid but modest sample. The large gaps (RAG's lift, LoRA's F1
  drop, the over-trigger ordering) are robust; a 2–3 point difference — e.g.
  Claude+RAG F1 0.857 vs stock 0.853 — is a tie, not a win.
- **This is the verdict task, not the agentic tool-loop** (stated above).
- **LoRA config:** 4-bit base, `--num-layers 8`, ~500 synthetic cases. A larger
  *real* corpus and a heavier adapter could shift the picture, but the realistic
  ceiling for this task is "match RAG," not beat it — which is why it's left as
  documented future work, not a live component.

## Reproduce

```bash
# full 6-arm matrix (needs Ollama + the mlx_lm.server LoRA endpoint)
LORA_MODEL_URL=http://localhost:8080/v1 LORA_MODEL=finetune/base-4bit \
op run --env-file=.env -- .venv/bin/python eval/run_eval.py --n 80 --matrix

# add just the LoRA arms to an existing run (same --n)
op run --env-file=.env -- .venv/bin/python eval/run_eval.py --lora-only --n 80
```

See `eval/LOCAL_MODEL.md` (Ollama arm) and `finetune/LORA.md` (fine-tune) for setup.
