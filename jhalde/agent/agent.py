"""
agent/agent.py
──────────────
AutoRedTeam Agent — autonomous pentest orchestrator.

The agent uses Claude claude-sonnet-4-6 with tool use to drive a full pentest
workflow: discover → enumerate → match CVEs → analyse → report.

Run:
    python3 -m agent.agent 192.168.56.101
    python3 -m agent.agent 192.168.56.101 --ports 1-65535
"""

import sys
import argparse
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

import config
from agent.tools import TOOL_DEFINITIONS, execute_tool
from agent.report import save_report
from agent.remediation import enhance_report
from agent.html_report import save_html_report

console = Console()

SYSTEM_PROMPT = """\
You are AutoRedTeam, an expert autonomous penetration testing agent.

Your mission: perform a structured security assessment of the given target and \
produce a professional pentest report.

Follow this workflow strictly:

### PHASE 1 — PASSIVE RECONNAISSANCE
1. Run whois_lookup on the target (always first)
2. Run dns_recon on the target (PTR/hostname for IPs; full DNS for domains)
3. Run theharvester_scan on the target (auto-skipped for IPs, useful for domains)

### PHASE 2 — ACTIVE SCANNING
4. Scan ports and services:
   - PREFER kali_recon(tool='nmap', ...) if Kali is reachable — richer options
   - FALLBACK to nmap_scan if Kali is unreachable
5. If web port found (80, 443, 8080) → kali_web_scan(tool='nikto') + kali_web_scan(tool='gobuster')
   or fallback nikto_scan + gobuster_scan
6. If port 139/445 open → kali_recon(tool='enum4linux-ng') or enum4linux_scan

### PHASE 3 — VULNERABILITY INTELLIGENCE
7. For each discovered service run:
   a. query_cve_database — find known CVEs from the RAG knowledge base
   b. searchsploit_lookup — find public ExploitDB exploits (use "service version" format)
8. Run analyze_cve_with_model on your top 2-3 CRITICAL CVEs
9. Run query_attack_techniques for the most critical findings

### PHASE 4 — EXPLOITATION
10. For each CRITICAL finding with a known MSF module:
    a. PREFER kali_exploit(tool='msfconsole', args=['use <module>; set RHOSTS <ip>; set LHOST <kali-ip>; run; exit'])
       FALLBACK to msf_run_exploit if Kali unavailable
    b. If session opened, run kali_post_exploit(tool='shell', args=['id && uname -a && ip addr'])
    c. Run kali_post_exploit(tool='shell', args=['cat /etc/passwd']) for user enumeration
    d. Run kali_post_exploit(tool='shell', args=['find / -perm -4000 -type f 2>/dev/null']) for SUID privesc
    e. OPTIONAL: kali_password_attack(tool='hydra', ...) against SSH with discovered usernames
       - "id" and "whoami" — confirm access level
       - "uname -a" — OS and kernel version
       - "cat /etc/passwd" — user accounts
       - "ip addr" — network interfaces for lateral movement
       - "find / -perm -4000 -type f 2>/dev/null" — SUID binaries for privesc

### PHASE 5 — REPORT
11. Write the comprehensive pentest report including exploitation evidence

TOOL NOTES:
- whois_lookup + dns_recon work on IP addresses too — always run them
- theharvester_scan: pass the target as "domain" — it auto-skips IPs
- searchsploit_lookup: "vsftpd 2.3.4", "samba 3.0.20", etc.
- analyze_cve_with_model: cite model_source in the finding (fine-tuned-llama or claude-haiku-fallback)
- enum4linux_scan: null session = CRITICAL; writable shares = CRITICAL; 35+ users = password spray risk

IMPORTANT RULES:
- NEVER suggest executing exploits — suggest and explain only
- Be specific: reference exact CVE IDs, CVSS scores, and service versions
- Prioritise findings by severity: CRITICAL > HIGH > MEDIUM > LOW
- The final report must use the exact format provided below

FINAL REPORT FORMAT (use this exact structure when writing your report):
# AutoRedTeam Pentest Report
**Target:** <IP or domain>
**Date:** <date>
**Assessed By:** AutoRedTeam AI Agent

## Executive Summary
<2-3 sentences summarising the risk posture>

## Reconnaissance
- **WHOIS:** <org, country, ASN, netblock>
- **Reverse DNS:** <hostname if found>
- **DNS Records:** <notable A/MX/NS/TXT records>
- **Subdomains found:** <list or "none">
- **OSINT (theHarvester):** <emails/hosts found or "skipped — IP target">

## Findings

### [CRITICAL/HIGH/MEDIUM/LOW] <Finding Title>
- **Service:** <port/service/version>
- **CVE:** <CVE-ID> (CVSS <score>)
- **ExploitDB:** <exploit title and EDB ID if found by searchsploit_lookup>
- **Description:** <what the vulnerability is>
- **Evidence:** <what was found>
- **Exploited:** <YES — session_id N opened / NO — not attempted or failed>
- **AI Analysis:** <summary from analyze_cve_with_model if called; include model_source>
- **Recommendation:** <how to fix>
- **ATT&CK:** <technique ID and name>

## Exploitation Evidence
(Include this section only if any msf_run_exploit calls succeeded)
### Session <N> — <module used>
- **Target:** <IP>
- **Session type:** shell / meterpreter
- **id output:** <result of 'id' command>
- **uname -a:** <kernel version>
- **SUID binaries:** <list or "none found">
- **Network interfaces:** <ip addr output>

## Risk Summary
| Severity | Count |
|----------|-------|
| CRITICAL | x |
| HIGH | x |
| MEDIUM | x |
| LOW | x |

## Remediation Priority
1. <Most urgent fix>
2. <Next>
3. <Next>
"""


def run_agent(target: str, ports: str = "1-1000") -> str:
    """
    Run the AutoRedTeam agent against a target.
    Returns the final pentest report as a string.
    """
    if not config.ANTHROPIC_API_KEY:
        console.print("[red]ANTHROPIC_API_KEY not set in .env[/]")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    console.print(Panel.fit(
        f"[bold cyan]AutoRedTeam Agent[/]\n"
        f"Target: [yellow]{target}[/]  |  Ports: [yellow]{ports}[/]\n"
        f"Started: [dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/]",
        border_style="cyan"
    ))

    messages = [
        {
            "role": "user",
            "content": (
                f"Perform a full security assessment of target: {target}\n"
                f"Scan port range: {ports}\n"
                f"Today's date: {datetime.now().strftime('%Y-%m-%d')}\n\n"
                "Start with nmap, then follow the workflow. "
                "When complete, write the full pentest report."
            ),
        }
    ]

    tool_call_count = 0
    final_report    = ""
    MAX_TOOL_CALLS  = 40   # force report after this many tool calls

    # ── Agentic loop ──────────────────────────────────────────
    while True:
        # Force report if agent is over-investigating
        if tool_call_count >= MAX_TOOL_CALLS:
            messages.append({
                "role": "user",
                "content": (
                    "You have gathered sufficient data. "
                    "STOP calling tools and write the full pentest report NOW "
                    "using the required format."
                )
            })

        for attempt in range(3):
            try:
                with Live(
                    Spinner("dots", text=Text(f" Thinking{'.' * (attempt+1)}", style="cyan")),
                    console=console,
                    transient=True,
                ):
                    response = client.messages.create(
                        model      = "claude-sonnet-4-6",
                        max_tokens = 8096,
                        system     = SYSTEM_PROMPT,
                        tools      = TOOL_DEFINITIONS,
                        messages   = messages,
                    )
                break
            except anthropic.APIConnectionError as e:
                if attempt == 2:
                    raise
                console.print(f"[yellow]Connection error, retrying ({attempt+1}/3)...[/]")
                import time; time.sleep(5)

        # ── Handle tool calls ──────────────────────────────
        if response.stop_reason == "tool_use":
            # Add assistant message with all tool use blocks
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_call_count += 1
                console.print(
                    f"\n[bold magenta][Tool {tool_call_count}][/] "
                    f"[cyan]{block.name}[/] "
                    f"[dim]{json.dumps(block.input)}[/]"
                )

                with Live(
                    Spinner("dots", text=Text(f" Running {block.name}...", style="yellow")),
                    console=console,
                    transient=True,
                ):
                    result = execute_tool(block.name, block.input)

                # Show a brief preview of the result
                preview = result[:200].replace("\n", " ")
                console.print(f"  [green]↳[/] [dim]{preview}...[/]")

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     result,
                })

            messages.append({"role": "user", "content": tool_results})

        # ── Final response (no more tool calls) ───────────
        elif response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    final_report += block.text

            console.print(
                f"\n[green]✓ Agent completed — {tool_call_count} tool calls made[/]"
            )
            break

        else:
            console.print(f"[yellow]Unexpected stop reason: {response.stop_reason}[/]")
            break

    return final_report


def main():
    parser = argparse.ArgumentParser(description="AutoRedTeam — AI Pentest Agent")
    parser.add_argument("target", help="Target IP address (e.g. 192.168.56.101)")
    parser.add_argument("--ports", default="1-1000", help="Port range (default: 1-1000)")
    args = parser.parse_args()

    report = run_agent(args.target, args.ports)

    if report:
        path = save_report(args.target, report)
        report = enhance_report(report, path)
        html_path = save_html_report(report, args.target, path)
        console.print(Panel.fit(
            f"[bold green]Reports saved:[/]\n"
            f"  Markdown: [cyan]{path}[/]\n"
            f"  HTML:     [cyan]{html_path}[/]",
            border_style="green"
        ))
        console.print("\n" + report)
    else:
        console.print("[red]Agent produced no report.[/]")


if __name__ == "__main__":
    main()
