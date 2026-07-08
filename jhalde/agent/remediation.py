"""
agent/remediation.py
─────────────────────
Post-processes the agent report and appends a structured
Remediation Playbook with specific fix commands and verification steps.
Uses Claude to generate playbook entries from the findings.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
import config

REMEDIATION_PROMPT = """\
You are a security remediation expert. Given a pentest report, extract each finding \
and produce a concrete Remediation Playbook section.

For each CRITICAL and HIGH finding, provide:
- The exact shell commands to remediate it (on Ubuntu/Debian Linux)
- The exact commands to VERIFY the fix worked
- Estimated effort: Quick (<1hr), Medium (1-4hr), or Involved (>4hr)

Use this exact format for each finding:

### Fix: <Finding Title>
**Severity:** CRITICAL/HIGH
**Effort:** Quick/Medium/Involved

**Remediation Commands:**
```bash
# commands here
```

**Verification Commands:**
```bash
# commands to confirm fix
```

---

Here is the pentest report:

{report}

Now write only the Remediation Playbook section. Start with:
## Remediation Playbook
"""


def generate_remediation_playbook(report: str) -> str:
    """Call Claude to generate a remediation playbook from the report."""
    if not config.ANTHROPIC_API_KEY:
        return ""

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Send only the findings section to keep tokens low
    findings_start = report.find("## Findings")
    risk_end = report.find("## Remediation Priority")
    if findings_start == -1:
        report_section = report
    else:
        report_section = report[findings_start:risk_end] if risk_end != -1 else report[findings_start:]

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": REMEDIATION_PROMPT.format(report=report_section)
        }]
    )
    return "\n\n" + msg.content[0].text.strip()


def enhance_report(report: str, path) -> str:
    """Append remediation playbook + exploit suggestions to report and save."""
    import re
    from rich.console import Console
    from agent.exploits import suggest_exploits, format_exploit_section
    console = Console()

    console.print("\n[cyan]Generating remediation playbook...[/]")
    playbook = generate_remediation_playbook(report)

    # Extract CVE IDs from report
    cve_ids = re.findall(r"CVE-\d{4}-\d+", report)

    # Build exploit suggestions (no services from report context, CVE-only match)
    suggestions = suggest_exploits([], cve_ids)
    exploit_section = format_exploit_section(suggestions)

    enhanced = report
    if playbook:
        enhanced += playbook
        console.print("[green]✓ Remediation playbook added[/]")
    if exploit_section:
        enhanced += exploit_section
        console.print(f"[green]✓ {len(suggestions)} exploit suggestion(s) added[/]")

    path.write_text(enhanced)
    return enhanced
