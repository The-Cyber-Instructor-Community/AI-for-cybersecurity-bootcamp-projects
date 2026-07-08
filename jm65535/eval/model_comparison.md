# Model comparison (86 held-out cases)

Ground-truth distribution: `{'ambiguous': 33, 'malicious': 39, 'benign': 14}`

Same single-shot triage verdict + same RAG context for every arm.

| arm | accuracy | malicious_f1 | over_trigger_rate | avg_latency |
|---|---|---|---|---|
| Claude | 0.651 | 0.733 | 0.383 | 2.89 |
| Claude + RAG | 0.802 | 0.857 | 0.191 | 3.08 |
| FoundationSec | 0.756 | 0.853 | 0.085 | 7.56 |
| FoundationSec + RAG | 0.709 | 0.831 | 0.128 | 11.0 |
| FoundationSec-LoRA | 0.674 | 0.727 | 0.064 | 6.53 |
| FoundationSec-LoRA + RAG | 0.663 | 0.754 | 0.085 | 9.72 |

- `Claude` = frontier model (`claude-sonnet-5`), Anthropic API, $/case.
- `FoundationSec` = `hf.co/gabriellarson/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M` — open, security-specialized 8B, on-prem via Ollama at $0/case, air-gapped.
- `FoundationSec-LoRA` = the same open 8B after LoRA fine-tuning on the judgment corpus (MLX); served via an OpenAI-compatible endpoint.

## What the columns mean

`n` = number of held-out test cases graded — each an unseen alert with a known analyst verdict. Larger `n` = more trustworthy percentages.

- `accuracy` — fraction of ALL cases labelled exactly right (verdict matched the analyst). Simple, but can hide missed threats.
- `malicious_f1` — single 0-1 score blending precision + recall — how well it handles the THREATS specifically. Higher = catches malware without crying wolf.
- `over_trigger_rate` — of NON-malicious cases, the fraction wrongly escalated to malicious — the false-alarm / alert-fatigue rate. LOWER is better.
- `avg_latency` — average seconds to decide one case (speed). Lower is faster.
