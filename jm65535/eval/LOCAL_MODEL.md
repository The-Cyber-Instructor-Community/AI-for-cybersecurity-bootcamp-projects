# Local model arm — Foundation-Sec-8B-Instruct via Ollama

We benchmark our **Claude + RAG** triage against **Foundation-Sec-8B-Instruct**, an
open, security-specialized 8B model (Cisco Foundation AI, continued-pretrained on a
cybersecurity corpus from Llama-3.1-8B). It runs fully **on-prem, air-gapped, at
$0/case** — the tradeoff foil to a frontier API.

We use the **Instruct** variant (not the base): the base model doesn't follow
instructions or emit structured verdicts without fine-tuning, so Instruct is the
fair, out-of-the-box baseline for our triage task.

## 1. Pull the model (one-time)

Ollama can pull the GGUF straight from Hugging Face:

```bash
ollama pull hf.co/gabriellarson/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M
```

Pick a smaller quant (e.g. `:Q4_K_S`) if memory is tight, or a larger one
(`:Q5_K_M`, `:Q8_0`) for a bit more fidelity. Whatever tag you pull, point the
harness at it with `LOCAL_MODEL` (below). Confirm it's there:

```bash
ollama list | grep -i foundation
```

## 2. Run the comparison

`--matrix` runs all four arms (Claude ±RAG, Foundation-Sec ±RAG) on the same
held-out set and writes `eval/model_comparison.md`:

```bash
# default LOCAL_MODEL matches the pull tag above; override if you used another quant
op run --env-file=.env -- .venv/bin/python eval/run_eval.py --n 30 --matrix
```

Just the local model, RAG on vs off:

```bash
op run --env-file=.env -- .venv/bin/python eval/run_eval.py --n 30 \
    --backend local --compare
```

## 3. Config (env, all optional)

| var | default | meaning |
|---|---|---|
| `LOCAL_MODEL` | `hf.co/gabriellarson/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M` | Ollama model tag |
| `LOCAL_MODEL_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint |
| `LOCAL_MODEL_KEY` | `ollama` | ignored by Ollama; any non-empty string |
| `LOCAL_MODEL_TIMEOUT` | `180` | seconds/request (raise it if on CPU) |

Example — a different quant, longer timeout:

```bash
LOCAL_MODEL=hf.co/gabriellarson/Foundation-Sec-8B-Instruct-GGUF:Q5_K_M \
LOCAL_MODEL_TIMEOUT=300 \
op run --env-file=.env -- .venv/bin/python eval/run_eval.py --n 30 --matrix
```

## Notes

- The comparison is the **single-shot verdict task** with the **same RAG context**
  for every arm — it isolates security *judgment*. We do **not** ask the 8B to drive
  the agentic multi-tool loop (native function-calling on the 8B-Instruct is not yet
  reliable); tool-use is validated on Claude in the live pipeline.
- Newer variants worth a look for a stretch comparison: **Foundation-Sec-1.1-8B-Instruct**
  (improved instruct) and **Foundation-Sec-8B-Reasoning** (open security reasoning model).
  Pull either and set `LOCAL_MODEL` to benchmark it — no code change.
- Fine-tuning is deliberately deferred: our 105-case corpus is better spent as RAG
  context than as SFT data. Decide on a LoRA pass *after* reading the baseline numbers.
