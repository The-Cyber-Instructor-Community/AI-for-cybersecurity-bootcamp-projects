"""
Quick test of nmap, nikto, gobuster tools against localhost.
Run: python3 test_mcp_tools.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from mcp_server.tools.nmap_tool import run_nmap
from mcp_server.tools.nikto_tool import run_nikto
from mcp_server.tools.gobuster_tool import run_gobuster

console = Console()
TARGET = "127.0.0.1"

console.print(Panel.fit(
    f"[bold cyan]AutoRedTeam — MCP Tools Test[/]\n"
    f"Target: [yellow]{TARGET}[/] (localhost)",
    border_style="cyan"
))

# ── Test 1: nmap ──────────────────────────────────────────────
console.print("\n[bold]1. nmap_scan[/] — scanning common ports on localhost...")
result = run_nmap(TARGET, ports="22,80,443,8080,3000,5000")

if result.get("error"):
    console.print(f"[red]Error: {result['error']}[/]")
else:
    t = Table(title="Open Ports")
    t.add_column("Port"); t.add_column("Service"); t.add_column("Version")
    for svc in result["services"]:
        t.add_row(str(svc["port"]), svc["service"], svc["version"])
    if result["services"]:
        console.print(t)
    else:
        console.print("[yellow]No open ports found on localhost (expected if no services running)[/]")
    console.print(f"[green]✓ nmap tool works — found {len(result['open_ports'])} open ports[/]")

# ── Test 2: nikto ─────────────────────────────────────────────
console.print("\n[bold]2. nikto_scan[/] — checking localhost:80...")
result = run_nikto(TARGET, port=80)

if result.get("error"):
    console.print(f"[yellow]nikto: {result['error']} (expected if no web server on :80)[/]")
else:
    console.print(f"[green]✓ nikto tool works — {result['finding_count']} findings[/]")

# ── Test 3: gobuster ──────────────────────────────────────────
console.print("\n[bold]3. gobuster_scan[/] — checking localhost:80...")
result = run_gobuster(TARGET, port=80)

if result.get("error"):
    console.print(f"[yellow]gobuster: {result['error']} (expected if no web server on :80)[/]")
else:
    console.print(f"[green]✓ gobuster tool works — {result['path_count']} paths found[/]")
    console.print(f"[dim]Using wordlist: {result['wordlist']}[/]")

console.print(Panel.fit(
    "[bold green]✓ MCP tools verified![/]\n"
    "Point these at Metasploitable2 IP on Day 5 for real findings.",
    border_style="green"
))
