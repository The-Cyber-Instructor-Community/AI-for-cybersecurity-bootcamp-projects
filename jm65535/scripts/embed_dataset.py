"""
Embed the labeled dataset into Chroma for retrieval at triage time.

Uses Chroma's built-in embedding function (all-MiniLM-L6-v2 via onnxruntime — the
model named in the project plan, without a PyTorch dependency). The situation text
is embedded; the label travels as metadata so retrieval returns the analyst's
verdict/action/rationale for similar past cases.

Run:  .venv/bin/python scripts/embed_dataset.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATASET = ROOT / "data" / "dataset.jsonl"
CHROMA_DIR = ROOT / "chroma_db"
COLLECTION = "soc_cases"


def main() -> None:
    import chromadb
    if not DATASET.exists():
        raise SystemExit("no data/dataset.jsonl — run scripts/generate_dataset.py first")
    records = [json.loads(ln) for ln in DATASET.read_text().splitlines() if ln.strip()]

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION)   # idempotent re-embed
    except Exception:
        pass
    col = client.create_collection(COLLECTION)

    col.add(
        ids=[r["id"] for r in records],
        documents=[r["situation"] for r in records],
        metadatas=[{
            "verdict": r["label"]["verdict"],
            "action": ", ".join(r["label"]["action"]),
            "rationale": r["label"]["rationale"],
            "technique": r["technique"],
            "signature": r["enrichment"].get("signature", ""),
            "is_true_positive": bool(r["label"].get("is_true_positive")),
        } for r in records],
    )
    print(f"embedded {len(records)} cases into Chroma collection '{COLLECTION}' at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
