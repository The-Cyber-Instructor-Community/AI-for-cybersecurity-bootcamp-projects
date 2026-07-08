"""
rag/ingest_attack.py
─────────────────────
Downloads MITRE ATT&CK Enterprise techniques and ingests them into ChromaDB.

Run: python -m rag.ingest_attack
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.utils import embedding_functions
from tqdm import tqdm
from rich.console import Console
from rich.panel import Panel

import config

# mitreattack-python provides a clean interface to the ATT&CK STIX data
try:
    from mitreattack.stix20 import MitreAttackData
except ImportError:
    print("Install mitreattack-python:  pip install mitreattack-python")
    sys.exit(1)

console = Console()

# ATT&CK STIX bundle URL (Enterprise, latest)
ATTACK_STIX_URL = (
    "https://raw.githubusercontent.com/mitre/cti/master/"
    "enterprise-attack/enterprise-attack.json"
)
STIX_LOCAL_PATH = config.DATA_DIR / "enterprise-attack.json"


def download_attack_stix():
    """Download the ATT&CK STIX bundle if not cached."""
    if STIX_LOCAL_PATH.exists():
        console.print(f"[green]✓ ATT&CK STIX already cached at {STIX_LOCAL_PATH}[/]")
        return

    import requests
    console.print("[cyan]Downloading MITRE ATT&CK Enterprise STIX bundle (~10 MB)...[/]")
    resp = requests.get(ATTACK_STIX_URL, stream=True, timeout=60)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    with open(STIX_LOCAL_PATH, "wb") as f, tqdm(
        total=total, unit="B", unit_scale=True, desc="ATT&CK STIX"
    ) as pbar:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            pbar.update(len(chunk))

    console.print(f"[green]✓ Saved to {STIX_LOCAL_PATH}[/]")


def _get_external_id(technique) -> str:
    """Extract ATT&CK ID (e.g. T1059) from STIX external_references."""
    for ref in getattr(technique, "external_references", []):
        source = getattr(ref, "source_name", "") or ref.get("source_name", "")
        eid = getattr(ref, "external_id", "") or ref.get("external_id", "")
        if source == "mitre-attack" and eid:
            return eid
    return "UNKNOWN"


def build_technique_document(technique) -> dict:
    """
    Convert a MITRE ATT&CK technique object into a ChromaDB document.
    """
    tid         = _get_external_id(technique)    # e.g. T1059
    name        = getattr(technique, "name", "")
    description = getattr(technique, "description", "") or ""
    tactics     = [p.phase_name for p in (getattr(technique, "kill_chain_phases", []) or [])]
    platforms   = getattr(technique, "x_mitre_platforms", []) or []
    is_subtechnique = "." in tid

    # Trim very long descriptions for embedding quality
    desc_short = description[:1500] if len(description) > 1500 else description

    text = (
        f"ATT&CK ID: {tid}\n"
        f"Name: {name}\n"
        f"Tactics: {', '.join(tactics)}\n"
        f"Platforms: {', '.join(platforms)}\n"
        f"Subtechnique: {'Yes' if is_subtechnique else 'No'}\n"
        f"Description: {desc_short}"
    )

    return {
        "id": f"attack-{tid}",
        "document": text,
        "metadata": {
            "attack_id":       tid,
            "name":            name,
            "tactics":         ", ".join(tactics),
            "platforms":       ", ".join(platforms),
            "is_subtechnique": str(is_subtechnique),
        }
    }


def ingest_attack():
    """Full pipeline: download → parse → embed → store."""

    console.print(Panel.fit(
        "[bold cyan]AutoRedTeam — MITRE ATT&CK Ingestion[/]\n"
        "Loading TTPs into your knowledge base...",
        border_style="cyan"
    ))

    # 1. Download STIX bundle
    download_attack_stix()

    # 2. Parse with mitreattack-python
    console.print("\n[cyan]Parsing ATT&CK techniques...[/]")
    attack_data = MitreAttackData(str(STIX_LOCAL_PATH))
    techniques  = attack_data.get_techniques(remove_revoked_deprecated=True)
    console.print(f"[green]✓ Found {len(techniques)} techniques (incl. subtechniques)[/]")

    # 3. Build documents
    docs = [build_technique_document(t) for t in techniques]

    # 4. Connect ChromaDB
    console.print(f"\n[cyan]Connecting to ChromaDB at {config.DB_DIR}...[/]")
    client = chromadb.PersistentClient(path=str(config.DB_DIR))

    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )

    collection = client.get_or_create_collection(
        name=config.ATTACK_COLLECTION,
        embedding_function=emb_fn,
        metadata={"hnsw:space": "cosine"}
    )

    # 5. Batch upsert
    console.print(f"\n[cyan]Embedding {len(docs)} ATT&CK techniques...[/]")
    BATCH = 50

    with tqdm(total=len(docs), desc="Embedding", unit="TTP") as pbar:
        for i in range(0, len(docs), BATCH):
            batch = docs[i : i + BATCH]
            collection.upsert(
                ids       = [d["id"] for d in batch],
                documents = [d["document"] for d in batch],
                metadatas = [d["metadata"] for d in batch],
            )
            pbar.update(len(batch))

    console.print(Panel.fit(
        f"[bold green]✓ Done![/]\n"
        f"Collection [cyan]{config.ATTACK_COLLECTION}[/] now has [bold]{collection.count()}[/] techniques.",
        border_style="green"
    ))


if __name__ == "__main__":
    ingest_attack()
