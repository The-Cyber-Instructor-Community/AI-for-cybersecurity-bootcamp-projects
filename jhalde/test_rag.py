"""
test_rag.py
────────────
Day 1 validation script. Run this after ingesting CVE + ATT&CK data
to confirm your RAG pipeline is working correctly.

Run: python test_rag.py
"""

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from rag.query import SecurityRAG

console = Console()


TEST_QUERIES = [
    # (description, service, vulnerability, cvss_score)
    (
        "vsftpd backdoor — classic Metasploitable2 finding",
        "vsftpd 2.3.4",
        "backdoor remote code execution",
        10.0
    ),
    (
        "Apache path traversal",
        "Apache HTTP Server 2.4.49",
        "path traversal directory listing",
        7.5
    ),
    (
        "OpenSSH username enumeration",
        "OpenSSH 7.2p2",
        "username enumeration timing attack",
        5.3
    ),
    (
        "SMB EternalBlue",
        "Microsoft SMBv1",
        "remote code execution buffer overflow",
        9.8
    ),
]


def run_tests():
    console.print(Panel.fit(
        "[bold cyan]AutoRedTeam — RAG Pipeline Test[/]\n"
        "Validating CVE + ATT&CK retrieval...",
        border_style="cyan"
    ))

    rag = SecurityRAG()
    rag.stats()
    console.print()

    passed = 0
    for desc, service, vuln, cvss in TEST_QUERIES:
        console.print(Rule(f"[bold]{desc}[/]"))
        console.print(f"[dim]Query: {service} | {vuln} | CVSS {cvss}[/]\n")

        enrichment = rag.enrich_finding(service, vuln, cvss, k=3)

        console.print(enrichment["summary"])
        console.print()

        if enrichment["cves"] or enrichment["ttps"]:
            console.print("[green]✓ Results returned[/]")
            passed += 1
        else:
            console.print("[red]✗ No results — check your ingestion[/]")

        console.print()

    console.print(Rule())
    color = "green" if passed == len(TEST_QUERIES) else "yellow"
    console.print(
        f"[{color}]Results: {passed}/{len(TEST_QUERIES)} queries returned results[/]"
    )

    if passed == len(TEST_QUERIES):
        console.print(Panel.fit(
            "[bold green]🎉 Day 1 Complete![/]\n"
            "Your RAG pipeline is working. Move on to Day 2: Fine-tuning.",
            border_style="green"
        ))
    else:
        console.print(
            "[yellow]Some queries returned no results.\n"
            "Make sure you ran both ingest scripts first:\n"
            "  python -m rag.ingest_cve\n"
            "  python -m rag.ingest_attack[/]"
        )


if __name__ == "__main__":
    run_tests()
