"""
agent/report.py
───────────────
Saves the agent's pentest report to a timestamped markdown file.
"""

import re
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

REPORTS_DIR = config.BASE_DIR / "reports"


def _safe_filename(target: str) -> str:
    """Convert any target (IP, domain, URL) to a safe filename segment."""
    # Strip URL scheme (https://, http://)
    target = re.sub(r'^https?://', '', target)
    # Replace any character that isn't alphanumeric, dash, or dot with underscore
    target = re.sub(r'[^a-zA-Z0-9\-\.]', '_', target)
    # Collapse multiple underscores and strip trailing ones
    target = re.sub(r'_+', '_', target).strip('_')
    return target[:80]  # cap length


def save_report(target: str, content: str) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_target = _safe_filename(target)
    path = REPORTS_DIR / f"report_{safe_target}_{timestamp}.md"
    path.write_text(content)
    return path


def _severity_counts(report: str) -> dict:
    """Parse severity counts from a report's Risk Summary table."""
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for sev in counts:
        m = re.search(rf'\|\s*{sev}\s*\|\s*(\d+)\s*\|', report, re.IGNORECASE)
        if m:
            counts[sev] = int(m.group(1))
    return counts


def save_cidr_summary(cidr: str, results: list) -> Path:
    """
    Write a combined summary report for a CIDR scan.
    `results` is a list of dicts: {host, report, path, html_path, error?}
    """
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_cidr = _safe_filename(cidr)
    path = REPORTS_DIR / f"report_cidr_{safe_cidr}_{timestamp}.md"

    scanned   = [r for r in results if r.get("report")]
    failed    = [r for r in results if not r.get("report")]
    total_c   = sum(_severity_counts(r["report"]).get("CRITICAL", 0) for r in scanned)
    total_h   = sum(_severity_counts(r["report"]).get("HIGH",     0) for r in scanned)
    total_m   = sum(_severity_counts(r["report"]).get("MEDIUM",   0) for r in scanned)
    total_l   = sum(_severity_counts(r["report"]).get("LOW",      0) for r in scanned)

    lines = [
        f"# AutoRedTeam CIDR Scan Summary",
        f"**Range:** {cidr}",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Assessed By:** AutoRedTeam AI Agent",
        "",
        "## Scope",
        f"- Hosts scanned: {len(results)}",
        f"- Reports generated: {len(scanned)}",
        f"- Hosts with no findings / errors: {len(failed)}",
        "",
        "## Aggregate Risk",
        "| Severity | Total |",
        "|----------|-------|",
        f"| CRITICAL | {total_c} |",
        f"| HIGH     | {total_h} |",
        f"| MEDIUM   | {total_m} |",
        f"| LOW      | {total_l} |",
        "",
        "## Per-Host Results",
        "| Host | CRIT | HIGH | MED | LOW | Report |",
        "|------|------|------|-----|-----|--------|",
    ]

    for r in results:
        if r.get("report"):
            c = _severity_counts(r["report"])
            report_link = str(r["path"]) if r.get("path") else "—"
            lines.append(
                f"| {r['host']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} "
                f"| {report_link} |"
            )
        else:
            err = r.get("error", "no report generated")
            lines.append(f"| {r['host']} | — | — | — | — | ERROR: {err} |")

    lines += ["", "## Individual Reports", ""]
    for r in scanned:
        lines.append(f"### {r['host']}")
        if r.get("path"):
            lines.append(f"- Markdown: `{r['path']}`")
        if r.get("html_path"):
            lines.append(f"- HTML: `{r['html_path']}`")
        lines.append("")

    path.write_text("\n".join(lines))
    return path
