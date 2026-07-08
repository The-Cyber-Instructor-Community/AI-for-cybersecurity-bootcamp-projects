"""
Build MLX-LM LoRA training data from the SAME case generator the eval uses.

Emits chat-format JSONL (system / user / assistant) that mirrors the eval triage
prompt EXACTLY but with NO RAG block — the point of fine-tuning is to bake the
judgment into weights instead of retrieving it at inference. Writes
finetune/data/{train,valid,test}.jsonl in the layout `mlx_lm.lora` expects.

Leakage firewall: the eval held-out set lives at generator index >=1000 (and
exception index >=500). We generate FT data strictly BELOW those indices, and the
generator embeds the index into every program path (hence the situation string),
so an FT case and a held-out case can never coincide. A printed overlap check
against a superset of the held-out situations asserts 0.

Run:  .venv/bin/python finetune/build_ft_data.py [--gen 600] [--exc-per 20]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from common import load_playbook  # noqa: E402
from generate_dataset import (gen_variant, exception_variant, shell_config_cases,  # noqa: E402
                              EXCEPTION_SPECS)

# Keep in sync with eval/run_eval.py DECIDE_SYSTEM (same input format => train on
# exactly what we evaluate on).
DECIDE_SYSTEM = (
    "You are a macOS SOC triage analyst. Using the playbook below and the "
    "already-collected enrichment findings, decide the verdict. Output ONLY JSON: "
    '{"verdict":"malicious|ambiguous|benign"}.'
)
OUT = ROOT / "finetune" / "data"


def _example(case: dict, system: str) -> dict:
    """One chat-format training row — matches eval predict() minus the RAG block."""
    user = (f"Situation: {case['situation']}\n"
            f"Enrichment findings: {json.dumps(case['enrichment'])}\n\n"
            "Decide the verdict.")
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": json.dumps({"verdict": case["label"]["verdict"]})},
    ]}


def _heldout_gen_situations(count: int = 600) -> set:
    """Superset of the eval held-out gen situations (same Random(7) sequence as
    eval/run_eval.heldout_set), for the leakage assertion."""
    rng = random.Random(7)
    return {gen_variant(1000 + i, rng)["situation"] for i in range(count)}


def _dist(cases: list[dict]) -> dict:
    d: dict[str, int] = {}
    for c in cases:
        v = c["label"]["verdict"]
        d[v] = d.get(v, 0) + 1
    return d


def build(gen_n: int, exc_per: int) -> None:
    playbook = load_playbook("T1547.011", "triage").body      # eval uses this for every case
    system = f"{DECIDE_SYSTEM}\n\n{playbook}"
    rng = random.Random(1234)

    cases: list[dict] = []
    seen: set[str] = set()

    def add(v: dict) -> None:
        if v["situation"] not in seen:
            seen.add(v["situation"])
            cases.append(v)

    for idx in range(gen_n):                                  # idx < 1000 => below held-out
        add(gen_variant(idx, rng))
    for spec in EXCEPTION_SPECS:
        for i in range(exc_per):                              # i < 500 => below held-out
            add(exception_variant(spec, i, rng))
    for v in shell_config_cases(rng):
        add(v)

    overlap = seen & _heldout_gen_situations()
    if overlap:
        raise SystemExit(f"LEAK: {len(overlap)} FT cases overlap the eval held-out set")

    rng.shuffle(cases)
    n = len(cases)
    n_valid = max(1, round(n * 0.12))
    n_test = max(1, round(n * 0.10))
    valid = cases[:n_valid]
    test = cases[n_valid:n_valid + n_test]
    train = cases[n_valid + n_test:]

    OUT.mkdir(parents=True, exist_ok=True)
    for name, split in (("train", train), ("valid", valid), ("test", test)):
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for c in split:
                f.write(json.dumps(_example(c, system)) + "\n")

    print(f"held-out overlap: {len(overlap)}  (must be 0)")
    print(f"train={len(train)}  valid={len(valid)}  test={len(test)}  -> {OUT}")
    print(f"train verdict dist: {_dist(train)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build MLX LoRA data from the case generator")
    ap.add_argument("--gen", type=int, default=600, help="generated T1547.011 cases (pre-dedupe)")
    ap.add_argument("--exc-per", type=int, default=20, help="instances per analyst-exception family")
    args = ap.parse_args()
    build(args.gen, args.exc_per)


if __name__ == "__main__":
    main()
