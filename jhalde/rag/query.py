"""
rag/query.py
─────────────
The RAG query interface used by the agent (and testable standalone).

Usage:
  from rag.query import SecurityRAG
  rag = SecurityRAG()
  results = rag.query_cves("vsftpd remote code execution")
  results = rag.query_attack("credential dumping windows")
  results = rag.enrich_finding("Apache 2.4.49", "Directory Traversal", 9.8)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.utils import embedding_functions
from dataclasses import dataclass
from rich.console import Console
from rich.table import Table

import config

console = Console()


@dataclass
class RAGResult:
    id: str
    text: str
    metadata: dict
    score: float   # cosine distance (lower = more similar)


class SecurityRAG:
    """
    Main RAG interface for AutoRedTeam.
    Wraps ChromaDB collections for CVEs and ATT&CK TTPs.
    """

    def __init__(self):
        client = chromadb.PersistentClient(path=str(config.DB_DIR))
        emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.EMBEDDING_MODEL
        )

        try:
            self.cve_collection = client.get_collection(
                name=config.CVE_COLLECTION,
                embedding_function=emb_fn
            )
        except Exception:
            self.cve_collection = None
            console.print("[yellow]⚠  CVE collection not found. Run: python -m rag.ingest_cve[/]")

        try:
            self.attack_collection = client.get_collection(
                name=config.ATTACK_COLLECTION,
                embedding_function=emb_fn
            )
        except Exception:
            self.attack_collection = None
            console.print("[yellow]⚠  ATT&CK collection not found. Run: python -m rag.ingest_attack[/]")

    def query_cves(self, query: str, k: int = config.TOP_K_RESULTS) -> list[RAGResult]:
        """Find the most relevant CVEs for a query."""
        if not self.cve_collection:
            return []

        results = self.cve_collection.query(
            query_texts=[query],
            n_results=min(k, self.cve_collection.count()),
        )
        return self._parse_results(results)

    def query_attack(self, query: str, k: int = config.TOP_K_RESULTS) -> list[RAGResult]:
        """Find the most relevant ATT&CK TTPs for a query."""
        if not self.attack_collection:
            return []

        results = self.attack_collection.query(
            query_texts=[query],
            n_results=min(k, self.attack_collection.count()),
        )
        return self._parse_results(results)

    def enrich_finding(
        self,
        service: str,
        vulnerability: str,
        cvss_score: float,
        k: int = 3
    ) -> dict:
        """
        Given a pentest finding, return relevant CVEs + ATT&CK TTPs.
        This is the core method the agent calls after each scan finding.

        Returns a dict with:
          - cves: list of RAGResult
          - ttps: list of RAGResult
          - summary: human-readable enrichment string
        """
        query = f"{service} {vulnerability} exploit"

        cves  = self.query_cves(query, k=k)
        ttps  = self.query_attack(f"{vulnerability} attack technique", k=k)

        # Build a summary string for the LLM to reason over
        lines = [f"=== Security Context for: {service} — {vulnerability} (CVSS {cvss_score}) ===\n"]

        if cves:
            lines.append("RELATED CVEs:")
            for r in cves:
                meta = r.metadata
                lines.append(
                    f"  • {meta.get('cve_id')} [{meta.get('severity')} {meta.get('score')}] "
                    f"— {r.text.split('Description:')[-1].strip()[:200]}"
                )
        else:
            lines.append("No matching CVEs found in database.")

        if ttps:
            lines.append("\nRELATED ATT&CK TTPs:")
            for r in ttps:
                meta = r.metadata
                lines.append(
                    f"  • {meta.get('attack_id')} — {meta.get('name')} "
                    f"[{meta.get('tactics')}]"
                )

        return {
            "cves": cves,
            "ttps": ttps,
            "summary": "\n".join(lines)
        }

    @staticmethod
    def _parse_results(raw: dict) -> list[RAGResult]:
        ids       = raw.get("ids", [[]])[0]
        documents = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]

        return [
            RAGResult(id=i, text=d, metadata=m, score=s)
            for i, d, m, s in zip(ids, documents, metadatas, distances)
        ]

    def stats(self):
        """Print collection stats."""
        table = Table(title="ChromaDB Collections", border_style="cyan")
        table.add_column("Collection", style="cyan")
        table.add_column("Documents", justify="right")

        cve_count    = self.cve_collection.count() if self.cve_collection else 0
        attack_count = self.attack_collection.count() if self.attack_collection else 0

        table.add_row(config.CVE_COLLECTION, str(cve_count))
        table.add_row(config.ATTACK_COLLECTION, str(attack_count))
        console.print(table)
