"""
RAG retrieval — inject the analyst's most similar past decisions into triage.

retrieve_similar(case) queries the Chroma collection built by
scripts/embed_dataset.py and returns a formatted block of the closest labeled
cases (verdict / action / rationale). The triage agent calls this before deciding
(hook in agents/triage_agent.py) so the model mirrors prior human judgment.

Degrades to "" if the collection isn't built yet, so triage still runs without RAG.
"""

from __future__ import annotations

from pathlib import Path

CHROMA_DIR = Path(__file__).resolve().parent / "chroma_db"
COLLECTION = "soc_cases"


def _collection():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_collection(COLLECTION)


def retrieve_by_text(query: str, k: int = 3) -> str:
    """Return a formatted block of the k most similar labeled cases for a query, or ''."""
    try:
        col = _collection()
        res = col.query(query_texts=[query], n_results=k)
    except Exception:
        return ""

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[None] * len(docs)])[0]
    if not docs:
        return ""

    lines = []
    for doc, meta, dist in zip(docs, metas, dists):
        sim = f"{1 - dist:.2f}" if isinstance(dist, (int, float)) else "?"
        lines.append(
            f"- (similarity {sim}) {doc}\n"
            f"    → analyst verdict: **{meta.get('verdict')}**, "
            f"action: {meta.get('action')}. Why: {meta.get('rationale')}"
        )
    return "\n".join(lines)


def retrieve_similar(case, k: int = 3) -> str:
    """Return a formatted block of the k most similar labeled cases for an alert, or ''."""
    query = (f"{' '.join(case.techniques)} {case.rule_description} "
             f"program {case.file_path or ''}")
    return retrieve_by_text(query, k)


if __name__ == "__main__":
    # quick manual check against the sample alert
    import json
    from common import CaseContext, techniques_for_alert
    alert = json.load(open(Path(__file__).parent / "data/sample_alerts/d1_suspicious.json"))
    c = CaseContext(alert=alert, techniques=techniques_for_alert(alert))
    print(retrieve_similar(c) or "(no results — build the index first)")
