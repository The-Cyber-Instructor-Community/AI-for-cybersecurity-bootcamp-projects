"""
rag/ingest_cve.py
─────────────────
Pulls CVEs from the NVD 2.0 API and ingests them into ChromaDB.

Run: python -m rag.ingest_cve
"""

import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
import chromadb
from chromadb.utils import embedding_functions
from tqdm import tqdm
from rich.console import Console
from rich.panel import Panel

import config

console = Console()


# ── Helpers ───────────────────────────────────────────────────

def get_cvss_score(cve_item: dict) -> float:
    """Extract highest available CVSS score from a CVE item."""
    metrics = cve_item.get("metrics", {})
    for key in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
        entries = metrics.get(key, [])
        if entries:
            try:
                return float(entries[0]["cvssData"]["baseScore"])
            except (KeyError, ValueError):
                pass
    return 0.0


def get_cvss_severity(cve_item: dict) -> str:
    """Extract severity string (CRITICAL / HIGH / MEDIUM / LOW)."""
    metrics = cve_item.get("metrics", {})
    for key in ["cvssMetricV31", "cvssMetricV30"]:
        entries = metrics.get(key, [])
        if entries:
            return entries[0]["cvssData"].get("baseSeverity", "UNKNOWN")
    return "UNKNOWN"


def get_description(cve_item: dict) -> str:
    """Get English description."""
    for d in cve_item.get("descriptions", []):
        if d.get("lang") == "en":
            return d.get("value", "").strip()
    return ""


def get_cwes(cve_item: dict) -> list[str]:
    """Extract CWE IDs."""
    cwes = []
    for w in cve_item.get("weaknesses", []):
        for d in w.get("description", []):
            val = d.get("value", "")
            if val.startswith("CWE-"):
                cwes.append(val)
    return cwes


def build_document(cve_item: dict) -> dict | None:
    """
    Convert raw NVD CVE item into a document dict for ChromaDB.
    Returns None if the CVE doesn't meet minimum quality bar.
    """
    cve_id  = cve_item.get("id", "")
    desc    = get_description(cve_item)
    score   = get_cvss_score(cve_item)
    severity = get_cvss_severity(cve_item)
    cwes    = get_cwes(cve_item)
    published = cve_item.get("published", "")[:10]

    if not desc or score < config.NVD_MIN_CVSS:
        return None

    # The text we embed — rich context helps retrieval
    text = (
        f"CVE ID: {cve_id}\n"
        f"Severity: {severity} (CVSS {score})\n"
        f"Published: {published}\n"
        f"CWE: {', '.join(cwes) if cwes else 'N/A'}\n"
        f"Description: {desc}"
    )

    return {
        "id":       cve_id,
        "document": text,
        "metadata": {
            "cve_id":    cve_id,
            "score":     score,
            "severity":  severity,
            "cwes":      ", ".join(cwes),
            "published": published,
        }
    }


# ── NVD Fetcher ───────────────────────────────────────────────

def fetch_nvd_cves(max_results: int = config.NVD_MAX_CVE) -> list[dict]:
    """
    Page through the NVD 2.0 API and return raw CVE items.
    Respects rate limits automatically.
    """
    headers = {}
    if config.NVD_API_KEY:
        headers["apiKey"] = config.NVD_API_KEY
        delay = 0.7    # 50 req/30s with key
    else:
        delay = 6.5    # 5 req/30s without key
        console.print("[yellow]⚠  No NVD_API_KEY set — using slow rate limit (6.5s between calls)[/]")
        console.print("[yellow]   Get a free key: https://nvd.nist.gov/developers/request-an-api-key[/]")

    all_items = []
    start_index = 0
    results_per_page = 2000   # NVD max per page

    console.print(f"\n[cyan]Fetching up to {max_results} CVEs from NVD (CVSS ≥ {config.NVD_MIN_CVSS})...[/]")

    with tqdm(total=max_results, unit="CVE") as pbar:
        while len(all_items) < max_results:
            params = {
                "startIndex":        start_index,
                "resultsPerPage":    min(results_per_page, max_results - len(all_items)),
                "cvssV3Severity":    "HIGH",   # pull HIGH + CRITICAL
            }
            # Remove severity filter if we want everything
            if config.NVD_MIN_CVSS < 7.0:
                params.pop("cvssV3Severity")

            for attempt in range(4):
                try:
                    resp = requests.get(
                        config.NVD_BASE_URL,
                        headers=headers,
                        params=params,
                        timeout=60
                    )
                    resp.raise_for_status()
                    break
                except requests.RequestException as e:
                    wait = 15 * (attempt + 1)
                    console.print(f"[red]NVD request failed (attempt {attempt+1}/4): {e}[/]")
                    if attempt < 3:
                        console.print(f"[yellow]Retrying in {wait}s...[/]")
                        time.sleep(wait)
            else:
                console.print("[red]All retries failed — stopping ingestion.[/]")
                break

            data = resp.json()
            vulnerabilities = data.get("vulnerabilities", [])
            if not vulnerabilities:
                break

            batch = [v["cve"] for v in vulnerabilities]
            all_items.extend(batch)
            pbar.update(len(batch))

            total_results = data.get("totalResults", 0)
            start_index += len(batch)

            if start_index >= total_results:
                break

            time.sleep(delay)

    console.print(f"[green]✓ Fetched {len(all_items)} raw CVEs[/]")
    return all_items


# ── Ingestor ──────────────────────────────────────────────────

def ingest_cves():
    """Full pipeline: fetch → filter → embed → store in ChromaDB."""

    console.print(Panel.fit(
        "[bold cyan]AutoRedTeam — CVE Ingestion[/]\n"
        "Building your security knowledge base...",
        border_style="cyan"
    ))

    # 1. Fetch raw CVEs
    raw_cves = fetch_nvd_cves(max_results=config.NVD_MAX_CVE)

    # 2. Build documents
    console.print("\n[cyan]Processing CVEs...[/]")
    docs = []
    for item in tqdm(raw_cves, desc="Parsing"):
        doc = build_document(item)
        if doc:
            docs.append(doc)

    console.print(f"[green]✓ {len(docs)} CVEs passed quality filter (CVSS ≥ {config.NVD_MIN_CVSS})[/]")

    if not docs:
        console.print("[red]No documents to ingest. Check NVD_MIN_CVSS in config.py[/]")
        return

    # 3. Connect to ChromaDB
    console.print(f"\n[cyan]Connecting to ChromaDB at {config.DB_DIR}...[/]")
    client = chromadb.PersistentClient(path=str(config.DB_DIR))

    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )

    collection = client.get_or_create_collection(
        name=config.CVE_COLLECTION,
        embedding_function=emb_fn,
        metadata={"hnsw:space": "cosine"}
    )

    # 4. Batch upsert (ChromaDB handles dedup via ID)
    console.print(f"\n[cyan]Embedding and storing {len(docs)} CVEs...[/]")
    BATCH = 100

    with tqdm(total=len(docs), desc="Embedding", unit="CVE") as pbar:
        for i in range(0, len(docs), BATCH):
            batch = docs[i : i + BATCH]
            collection.upsert(
                ids        = [d["id"] for d in batch],
                documents  = [d["document"] for d in batch],
                metadatas  = [d["metadata"] for d in batch],
            )
            pbar.update(len(batch))

    final_count = collection.count()
    console.print(Panel.fit(
        f"[bold green]✓ Done![/]\n"
        f"Collection [cyan]{config.CVE_COLLECTION}[/] now has [bold]{final_count}[/] CVEs.\n"
        f"DB path: [dim]{config.DB_DIR}[/]",
        border_style="green"
    ))


if __name__ == "__main__":
    ingest_cves()
