"""
Evaluation harness — measures the triage agent's decision quality on a HELD-OUT
set (generated with a different seed than the RAG corpus, so we test
generalization, not memorization).

For each held-out case we give the triage LLM the playbook + the already-collected
enrichment findings (isolating the decision layer; tool-calling is validated
separately on real cases) and compare its verdict to the analyst ground truth.
Runs twice — WITH and WITHOUT RAG — to quantify RAG's contribution.

Metrics: accuracy, malicious precision/recall/F1, and over-trigger rate
(non-malicious cases the agent wrongly escalates to malicious).

Run (needs the Claude key + the Chroma index built):
    op run --env-file=.env -- .venv/bin/python eval/run_eval.py --n 20 --compare
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval"))

from common import load_playbook, extract_json, TRIAGE_MODEL  # noqa: E402
import rag  # noqa: E402
import backends  # noqa: E402
from generate_dataset import gen_variant, EXCEPTION_SPECS, exception_variant  # noqa: E402

VERDICTS = ("malicious", "ambiguous", "benign")


# --------------------------------------------------------------------------- #
# Held-out set (different seed; excludes anything already in the RAG corpus)
# --------------------------------------------------------------------------- #

def heldout_set(n: int, seed: int = 7) -> list[dict]:
    train_situations = set()
    ds = ROOT / "data" / "dataset.jsonl"
    if ds.exists():
        train_situations = {json.loads(l)["situation"] for l in ds.read_text().splitlines() if l.strip()}
    rng = random.Random(seed)
    out, i = [], 0
    while len(out) < n:
        v = gen_variant(1000 + i, rng)
        i += 1
        if v["situation"] in train_situations:
            continue
        out.append(v)
    return out


def exception_heldout(per: int = 3, seed: int = 11) -> list[dict]:
    """Held-out instances of the analyst-exception cases — NEW instances (different
    idx) that share the marker, so RAG can match the corpus and recover them while
    the playbook alone follows the naive rule (and gets them wrong)."""
    rng = random.Random(seed)
    return [exception_variant(spec, 500 + i, rng) for spec in EXCEPTION_SPECS for i in range(per)]


# --------------------------------------------------------------------------- #
# Decision (the model call) and metrics (pure, testable without the API)
# --------------------------------------------------------------------------- #

DECIDE_SYSTEM = (
    "You are a macOS SOC triage analyst. Using the playbook below and the "
    "already-collected enrichment findings, decide the verdict. Output ONLY JSON: "
    '{"verdict":"malicious|ambiguous|benign"}.'
)

_VERDICT_RE = re.compile(r'verdict["\s:=]{0,4}(malicious|ambiguous|benign)', re.I)


def _parse_verdict(text: str) -> str:
    """JSON first; then a light fallback so we grade JUDGMENT, not JSON formatting
    (fair to smaller open models that sometimes wrap or narrate the answer)."""
    v = (extract_json(text).get("verdict") or "").lower()
    if v in VERDICTS:
        return v
    m = _VERDICT_RE.search(text)
    if m:
        return m.group(1).lower()
    hits = [k for k in VERDICTS if k in text.lower()]
    return hits[0] if len(hits) == 1 else "ambiguous"


def predict(case: dict, *, backend: str, model_id: str, with_rag: bool) -> str:
    playbook = load_playbook("T1547.011", "triage").body
    rag_block = rag.retrieve_by_text(case["situation"]) if with_rag else ""
    prompt = (f"Situation: {case['situation']}\n"
              f"Enrichment findings: {json.dumps(case['enrichment'])}\n\n"
              + (f"Similar past cases the analyst already labeled:\n{rag_block}\n\n" if rag_block else "")
              + "Decide the verdict.")
    text = backends.complete(backend=backend, model=model_id,
                             system=f"{DECIDE_SYSTEM}\n\n{playbook}",
                             prompt=prompt, max_tokens=300)
    return _parse_verdict(text)


def compute_metrics(pairs: list[tuple[str, str]]) -> dict:
    """pairs = list of (ground_truth, predicted)."""
    n = len(pairs)
    correct = sum(gt == pr for gt, pr in pairs)
    tp = sum(gt == "malicious" and pr == "malicious" for gt, pr in pairs)
    fp = sum(gt != "malicious" and pr == "malicious" for gt, pr in pairs)
    fn = sum(gt == "malicious" and pr != "malicious" for gt, pr in pairs)
    non_mal = sum(gt != "malicious" for gt, pr in pairs)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "n": n,
        "accuracy": round(correct / n, 3) if n else 0.0,
        "malicious_precision": round(prec, 3),
        "malicious_recall": round(rec, 3),
        "malicious_f1": round(f1, 3),
        "over_trigger_rate": round(fp / non_mal, 3) if non_mal else 0.0,
    }


# Plain-English one-liners so the saved results are self-explanatory in a write-up.
METRIC_GLOSS = {
    "accuracy": "fraction of ALL cases labelled exactly right (verdict matched the "
                "analyst). Simple, but can hide missed threats.",
    "malicious_precision": "when it says \"malicious\", how often it really is "
                           "(guards against false alarms).",
    "malicious_recall": "of all truly-malicious cases, how many it caught "
                        "(guards against misses — the dangerous failure).",
    "malicious_f1": "single 0-1 score blending precision + recall — how well it "
                    "handles the THREATS specifically. Higher = catches malware "
                    "without crying wolf.",
    "over_trigger_rate": "of NON-malicious cases, the fraction wrongly escalated to "
                         "malicious — the false-alarm / alert-fatigue rate. LOWER is better.",
    "avg_latency": "average seconds to decide one case (speed). Lower is faster.",
}


def _glossary_md(cols: tuple[str, ...]) -> list[str]:
    """Markdown 'what the columns mean' block for the given metric columns."""
    out = ["", "## What the columns mean", "",
           "`n` = number of held-out test cases graded — each an unseen alert with a "
           "known analyst verdict. Larger `n` = more trustworthy percentages.", ""]
    out += [f"- `{c}` — {METRIC_GLOSS[c]}" for c in cols if c in METRIC_GLOSS]
    return out


def matrix_md(n_cases: int, gt_dist: dict, results: dict, cols: tuple[str, ...],
              local_id: str) -> str:
    """Assemble the model-comparison markdown (single source of truth for the file)."""
    md = [f"# Model comparison ({n_cases} held-out cases)", "",
          f"Ground-truth distribution: `{gt_dist}`", "",
          "Same single-shot triage verdict + same RAG context for every arm.", "",
          "| arm | " + " | ".join(cols) + " |",
          "|---|" + "|".join("---" for _ in cols) + "|"]
    for name, m in results.items():
        md.append(f"| {name} | " + " | ".join(str(m[c]) for c in cols) + " |")
    md += ["",
           f"- `Claude` = frontier model (`{TRIAGE_MODEL}`), Anthropic API, $/case.",
           f"- `FoundationSec` = `{local_id}` — open, security-specialized 8B, "
           "on-prem via Ollama at $0/case, air-gapped."]
    if any("LoRA" in n for n in results):
        md.append("- `FoundationSec-LoRA` = the same open 8B after LoRA fine-tuning on the "
                  "judgment corpus (MLX); served via an OpenAI-compatible endpoint.")
    md += _glossary_md(cols)
    return "\n".join(md) + "\n"


def run(cases: list[dict], *, backend: str = "claude", model_id: str = TRIAGE_MODEL,
        with_rag: bool) -> dict:
    pairs, t0 = [], time.time()
    for c in cases:
        pred = predict(c, backend=backend, model_id=model_id, with_rag=with_rag)
        pairs.append((c["label"]["verdict"], pred))
    m = compute_metrics(pairs)
    m["avg_latency"] = round((time.time() - t0) / len(cases), 2) if cases else 0.0
    return m


MATRIX_JSON = ROOT / "eval" / "model_comparison.json"

# Canonical column order for the merged table.
ARM_ORDER = ["Claude", "Claude + RAG", "FoundationSec", "FoundationSec + RAG",
             "FoundationSec-LoRA", "FoundationSec-LoRA + RAG"]


def _ordered(results: dict) -> dict:
    """Arms in canonical order, with any unexpected names appended at the end."""
    out = {k: results[k] for k in ARM_ORDER if k in results}
    for k in results:
        out.setdefault(k, results[k])
    return out


def _print_matrix_table(results: dict, cols: tuple[str, ...]) -> None:
    hdr = f"{'arm':<24}" + "".join(f"{c:>19}" for c in cols)
    lines = [hdr, "-" * len(hdr)]
    for name, m in results.items():
        lines.append(f"{name:<24}" + "".join(f"{m[c]:>19}" for c in cols))
    print("\n" + "\n".join(lines), flush=True)


def _save_matrix(n_cases: int, gt_dist: dict, results: dict, cols: tuple[str, ...],
                 local_id: str) -> None:
    """Persist both the machine-readable JSON (for incremental arm adds) and the MD."""
    results = _ordered(results)
    MATRIX_JSON.write_text(json.dumps(
        {"n_cases": n_cases, "gt_dist": gt_dist, "cols": list(cols),
         "local_id": local_id, "arms": results}, indent=2), encoding="utf-8")
    (ROOT / "eval" / "model_comparison.md").write_text(
        matrix_md(n_cases, gt_dist, results, cols, local_id), encoding="utf-8")


def run_lora_only(cases: list[dict], gt_dist: dict) -> None:
    """Run ONLY the LoRA arms and merge into the existing saved matrix — avoids
    re-running the other arms. Valid because the held-out set is deterministic
    (fixed seeds + same --n) so the cases are identical across runs."""
    if not MATRIX_JSON.exists():
        print("no saved matrix at eval/model_comparison.json — run a full --matrix "
              "once first, then --lora-only can extend it.", flush=True)
        return
    prev = json.loads(MATRIX_JSON.read_text())
    if prev.get("n_cases") != len(cases):
        print(f"case count differs (saved {prev.get('n_cases')} vs now {len(cases)}); "
              "not comparable — re-run full --matrix with the same --n, or match --n.",
              flush=True)
        return
    if not backends.lora_configured():
        print("LORA_MODEL not set — nothing to add. See finetune/LORA.md.", flush=True)
        return
    ok, msg = backends.health("lora")
    print(f"[lora]  {msg}", flush=True)
    if not ok:
        print("[lora]  unreachable — start mlx_lm.server (see finetune/LORA.md).", flush=True)
        return

    lid = backends.resolve_model("lora")
    cols = tuple(prev.get("cols", ("accuracy", "malicious_f1", "over_trigger_rate", "avg_latency")))
    results = dict(prev.get("arms", {}))
    for name, rag_on in (("FoundationSec-LoRA", False), ("FoundationSec-LoRA + RAG", True)):
        print(f"  running arm: {name:<24} ...", flush=True)
        results[name] = run(cases, backend="lora", model_id=lid, with_rag=rag_on)

    results = _ordered(results)
    _print_matrix_table(results, cols)
    _save_matrix(len(cases), gt_dist, results, cols, prev.get("local_id", backends.local_model_id()))
    print("\nmerged LoRA arms -> eval/model_comparison.md (+ .json)", flush=True)


def run_matrix(cases: list[dict], gt_dist: dict) -> None:
    """Cross-product benchmark: Claude vs Foundation-Sec-8B-Instruct, each ±RAG.

    The comparison is the SAME single-shot verdict task with the SAME RAG context —
    it isolates security judgment, not tool-calling (an 8B won't drive the agentic
    tool loop reliably, so that's validated on Claude separately).
    """
    local_id = backends.local_model_id()
    arms = [
        ("Claude",             "claude", TRIAGE_MODEL, False),
        ("Claude + RAG",       "claude", TRIAGE_MODEL, True),
        ("FoundationSec",      "local",  local_id,     False),
        ("FoundationSec + RAG", "local", local_id,     True),
    ]
    ok, msg = backends.health("local")
    print(f"[local] {msg}")
    if not ok:
        print("[local] skipping Foundation-Sec arms — start Ollama + pull the model "
              "(see eval/LOCAL_MODEL.md), then re-run.\n", flush=True)
        arms = [a for a in arms if a[1] != "local"]

    # Opt-in LoRA arms: only when LORA_MODEL is set and its endpoint is reachable
    # (the fine-tune served via mlx_lm.server — see finetune/LORA.md).
    if backends.lora_configured():
        lok, lmsg = backends.health("lora")
        print(f"[lora]  {lmsg}")
        if lok:
            lid = backends.resolve_model("lora")   # exact served id (adapter applied)
            arms += [("FoundationSec-LoRA", "lora", lid, False),
                     ("FoundationSec-LoRA + RAG", "lora", lid, True)]
        else:
            print("[lora]  configured but unreachable — skipping (see finetune/LORA.md).\n",
                  flush=True)

    results: dict[str, dict] = {}
    for name, backend, mid, rag_on in arms:
        print(f"  running arm: {name:<24} ...", flush=True)
        results[name] = run(cases, backend=backend, model_id=mid, with_rag=rag_on)

    cols = ("accuracy", "malicious_f1", "over_trigger_rate", "avg_latency")
    _print_matrix_table(results, cols)
    _save_matrix(len(cases), gt_dist, results, cols, local_id)
    print("\nsaved -> eval/model_comparison.md (+ .json)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Triage eval harness")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--no-rag", action="store_true", help="evaluate without RAG")
    ap.add_argument("--compare", action="store_true",
                    help="run the chosen --backend both with and without RAG")
    ap.add_argument("--backend", choices=["claude", "local"], default="claude",
                    help="claude (Anthropic API) or local (Foundation-Sec via Ollama)")
    ap.add_argument("--model-id", default=None,
                    help="override the model tag/id for the chosen backend")
    ap.add_argument("--matrix", action="store_true",
                    help="benchmark ALL arms: Claude ±RAG vs Foundation-Sec ±RAG")
    ap.add_argument("--lora-only", action="store_true",
                    help="run ONLY the LoRA arms and merge into the saved matrix "
                         "(use the same --n as the original --matrix run)")
    ap.add_argument("--selftest", action="store_true", help="test metrics math only (no API)")
    args = ap.parse_args()

    model_id = args.model_id or (TRIAGE_MODEL if args.backend == "claude"
                                 else backends.local_model_id())

    if args.selftest:
        demo = [("malicious", "malicious"), ("benign", "malicious"),
                ("benign", "benign"), ("malicious", "ambiguous"), ("ambiguous", "ambiguous")]
        print("selftest metrics:", json.dumps(compute_metrics(demo), indent=2))
        return

    exc = exception_heldout()
    cases = heldout_set(args.n) + exc
    gt_dist: dict[str, int] = {}
    for c in cases:
        gt_dist[c["label"]["verdict"]] = gt_dist.get(c["label"]["verdict"], 0) + 1
    print(f"held-out cases: {len(cases)} ({len(exc)} analyst-exception cases where the "
          f"naive rule is wrong) | ground-truth dist: {gt_dist}\n")

    metric_keys = ("accuracy", "malicious_precision", "malicious_recall",
                   "malicious_f1", "over_trigger_rate")

    if args.lora_only:
        run_lora_only(cases, gt_dist)
        return

    if args.matrix:
        run_matrix(cases, gt_dist)
        return

    if args.compare:
        without = run(cases, backend=args.backend, model_id=model_id, with_rag=False)
        withr = run(cases, backend=args.backend, model_id=model_id, with_rag=True)
        lines = [f"{'metric':<22}{'no-RAG':>10}{'with-RAG':>12}{'Δ':>8}"]
        for k in metric_keys:
            d = round(withr[k] - without[k], 3)
            lines.append(f"{k:<22}{without[k]:>10}{withr[k]:>12}{d:>+8}")
        print("\n".join(lines), flush=True)

        # persist a README-ready markdown table (survives any terminal truncation)
        md = [f"# Eval results ({len(cases)} held-out cases, {len(exc)} analyst-exception)",
              "", f"Ground-truth distribution: {gt_dist}", "",
              "| metric | no-RAG | with-RAG | Δ |", "|---|---|---|---|"]
        for k in metric_keys:
            md.append(f"| {k} | {without[k]} | {withr[k]} | {withr[k]-without[k]:+.3f} |")
        md += _glossary_md(metric_keys)
        (ROOT / "eval" / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        print(f"\nfull results saved -> eval/results.md", flush=True)
    else:
        m = run(cases, backend=args.backend, model_id=model_id, with_rag=not args.no_rag)
        print(f"[{args.backend}] {'RAG on' if not args.no_rag else 'RAG off'}:",
              json.dumps(m, indent=2), flush=True)


if __name__ == "__main__":
    main()
