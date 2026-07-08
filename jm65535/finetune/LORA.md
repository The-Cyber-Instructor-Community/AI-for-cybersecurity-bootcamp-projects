# LoRA fine-tune experiment — Foundation-Sec-8B-Instruct on Apple Silicon (MLX)

An **experiment**, framed honestly: with a small corpus, RAG usually beats
fine-tuning (see the write-up below). We run LoRA anyway to *measure* that, and to
see whether baking the judgment into weights closes Foundation-Sec's recall gap to
Claude+RAG. Expected outcome: RAG-competitive at best. The learning is the point.

Everything here runs locally on an M-series Mac — no CUDA, no cloud. The fine-tuned
model plugs into the eval as extra arms (`FoundationSec-LoRA ±RAG`) with **no code
change** — it's just a second OpenAI-compatible endpoint.

## Prerequisites

```bash
# a separate env keeps the heavy ML deps out of the project venv
python3 -m venv ~/.venvs/mlx && source ~/.venvs/mlx/bin/activate
pip install -U mlx-lm
# mlx-lm 0.31.3 requires transformers>=5.0.0 but CRASHES on transformers 5.13+
# (a register() API regression: "'str' object has no attribute '__module__'").
# Pin to the 5.x the ecosystem is built against:
pip install "transformers==5.0.0"
```

Verify the pin took (should print 5.0.0, and `mlx_lm.lora --help` should run):

```bash
python -c "import transformers; print(transformers.__version__)"
mlx_lm.lora --help >/dev/null && echo "mlx-lm imports OK"
```

Memory note: the base model is ~8B. In fp16 the weights alone are ~16 GB, which
OOMs the GPU on a 16 GB Mac before training even starts (Metal
`kIOGPUCommandBufferCallbackErrorOutOfMemory`). On ≤16 GB, use the 4-bit path
below — it is the default here, not a fallback.

## Step 0 — build the training data

Reuses the exact case generator + eval prompt format, minus the RAG block. Writes
`finetune/data/{train,valid,test}.jsonl` and asserts zero overlap with the eval
held-out set. (Run from the project venv — it only needs stdlib + the repo.)

```bash
.venv/bin/python finetune/build_ft_data.py --gen 600 --exc-per 20
# -> held-out overlap: 0 (must be 0)
#    train=~510  valid=~70  test=~60
```

## Step 1 — train the LoRA adapter

**Recommended (≤16 GB Mac) — 4-bit base + memory-lean flags.** First quantize the
base to 4-bit (reuses the HF cache, no re-download; ~4.5 GB weights):

```bash
mlx_lm.convert --hf-path fdtn-ai/Foundation-Sec-8B-Instruct -q --mlx-path finetune/base-4bit
```

If this fails at the save step with `IncompleteSnapshotError` (the training run
only cached the files needed to *load* the model, not the whole repo), complete
the snapshot first — weights are cached, so this only pulls the small
tokenizer/license files — then re-run the convert above:

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download('fdtn-ai/Foundation-Sec-8B-Instruct')"
```

Then train against it. `--grad-checkpoint` recomputes activations in the backward
pass (trades compute for a big memory saving); `--batch-size 1` and
`--max-seq-length 1024` keep activation memory small:

```bash
mlx_lm.lora --model finetune/base-4bit --train --data finetune/data \
  --adapter-path finetune/adapters --iters 400 \
  --batch-size 1 --num-layers 8 --max-seq-length 1024 \
  --grad-checkpoint --learning-rate 1e-5
```

Free memory first: quit other heavy apps and unload any Ollama model
(`ollama stop <model>` or quit Ollama) — unified memory is shared with the GPU.

**32 GB+ Mac** can skip quantization and raise throughput:

```bash
mlx_lm.lora --model fdtn-ai/Foundation-Sec-8B-Instruct --train --data finetune/data \
  --adapter-path finetune/adapters --iters 400 --batch-size 2 --num-layers 8 \
  --grad-checkpoint --learning-rate 1e-5
```

Keep it light — small data overfits fast: low rank (few `--num-layers`), 1–3 epochs
worth of `--iters`, low LR. Start with `--iters 200` as a smoke test, watch the
validation loss, then extend. Adapters land in `finetune/adapters/` (git-ignored).

**Still hitting Metal OOM?** In order of impact: (1) confirm you're on the 4-bit
`finetune/base-4bit`, not the HF fp16 path; (2) `--max-seq-length 512`;
(3) `--num-layers 4`; (4) as a last resort raise the GPU wired-memory cap —
`sudo sysctl iogpu.wired_limit_mb=13000` (leave ~3 GB for the OS; resets on reboot).

Optional — check held-out test loss:

```bash
mlx_lm.lora --model finetune/base-4bit \
  --data finetune/data --test --adapter-path finetune/adapters --max-seq-length 1024
```

## Step 2 — serve it (recommended: no fuse/convert needed)

`mlx_lm.server` is OpenAI-compatible, so the eval's local backend talks to it
directly. Serve the SAME 4-bit base you trained against + the adapter on port 8080
(fp16 serving would OOM on 16 GB just like training did):

```bash
mlx_lm.server --model finetune/base-4bit \
  --adapter-path finetune/adapters --port 8080
```

## Step 3 — benchmark as the 5th/6th arm

In another terminal, point the `lora` backend at the mlx server. Because
`LORA_MODEL` is set, the matrix auto-adds `FoundationSec-LoRA ±RAG`:

```bash
LORA_MODEL_URL=http://localhost:8080/v1 \
LORA_MODEL=finetune/base-4bit \
op run --env-file=.env -- .venv/bin/python eval/run_eval.py --n 80 --matrix
```

You'll now see six arms in the table and `eval/model_comparison.md`:
Claude ±RAG, FoundationSec ±RAG, **FoundationSec-LoRA ±RAG**.

## Alternative — bake a permanent Ollama tag (fuse → GGUF → ollama create)

If you'd rather have a standing Ollama model instead of running the mlx server:

```bash
# 1. fuse the adapter into a standalone HF-format model
mlx_lm.fuse --model fdtn-ai/Foundation-Sec-8B-Instruct \
  --adapter-path finetune/adapters --save-path finetune/fused

# 2. convert to GGUF + quantize (needs a llama.cpp checkout)
python llama.cpp/convert_hf_to_gguf.py finetune/fused \
  --outfile finetune/foundation-sec-lora-f16.gguf --outtype f16
llama.cpp/llama-quantize finetune/foundation-sec-lora-f16.gguf \
  finetune/foundation-sec-lora-q4.gguf Q4_K_M

# 3. register with Ollama (Modelfile: `FROM ./foundation-sec-lora-q4.gguf`)
ollama create foundation-sec-lora -f finetune/Modelfile
```

Then benchmark against Ollama (:11434) instead of the mlx server:

```bash
LORA_MODEL_URL=http://localhost:11434/v1 LORA_MODEL=foundation-sec-lora \
op run --env-file=.env -- .venv/bin/python eval/run_eval.py --n 80 --matrix
```

## Reading the result

- **If LoRA ≈ or < FoundationSec+RAG:** expected. RAG already captured the
  judgment; small-data fine-tuning re-learned it at best. That's a legitimate,
  defensible capstone finding — say so.
- **If LoRA+RAG > everything:** the fine-tune added recall on top of retrieval —
  a real win worth a slide (and a case for a bigger labeled set).
- **Watch for overfitting:** strong on `test.jsonl` loss but weak on the eval
  held-out set = it memorized the generator, didn't generalize. Grow the data
  (`--gen`) or train lighter.

## Why this is a fair test

- Same single-shot verdict task + same prompt format as every other arm.
- FT data is disjoint from the eval held-out set (index firewall + asserted 0 overlap).
- LoRA arm runs both without RAG (judgment-in-weights) and with RAG (weights + retrieval).
