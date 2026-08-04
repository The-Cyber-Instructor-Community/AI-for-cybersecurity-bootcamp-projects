"""
agent/memory.py
───────────────
SQLite-backed agentic memory for AutoRedTeam.

Persists scan history across runs so the agent can:
  - Know what it found on a target previously
  - Avoid redundant re-scanning
  - Build cumulative intelligence about a target over time

DB location: <project_root>/autoredteam_memory.db
"""

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

DB_PATH = config.BASE_DIR / "autoredteam_memory.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet."""
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                target      TEXT NOT NULL,
                scanned_at  TEXT NOT NULL,
                ports_open  TEXT,
                services    TEXT,
                crit        INTEGER DEFAULT 0,
                high        INTEGER DEFAULT 0,
                medium      INTEGER DEFAULT 0,
                low         INTEGER DEFAULT 0,
                report_path TEXT
            );

            CREATE TABLE IF NOT EXISTS findings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id     INTEGER NOT NULL REFERENCES scans(id),
                severity    TEXT,
                title       TEXT,
                cve         TEXT,
                service     TEXT,
                description TEXT
            );
        """)


# ── Parsing helpers ──────────────────────────────────────────

def _parse_severity_counts(report: str) -> dict:
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for sev in counts:
        m = re.search(rf'\|\s*{sev}\s*\|\s*(\d+)\s*\|', report, re.IGNORECASE)
        if m:
            counts[sev] = int(m.group(1))
    return counts


def _parse_open_ports(report: str) -> str:
    """Extract open port list from nmap-style output or ## Findings headings."""
    ports = re.findall(r'\b(\d{1,5}/(?:tcp|udp))\b', report)
    seen = []
    for p in ports:
        if p not in seen:
            seen.append(p)
    return ", ".join(seen[:20])  # cap at 20


def _parse_services(report: str) -> str:
    """Extract service/version strings mentioned in the report."""
    svcs = re.findall(
        r'\*\*Service:\*\*\s*([^\n]+)',
        report, re.IGNORECASE
    )
    return "; ".join(s.strip() for s in svcs[:10])


def _parse_findings(report: str) -> list[dict]:
    """
    Extract individual findings from ## Findings section.
    Looks for ### [SEVERITY] Title blocks.
    """
    findings = []
    pattern = re.compile(
        r'###\s+\[?(CRITICAL|HIGH|MEDIUM|LOW)\]?\s+(.+?)\n'
        r'(.*?)'
        r'(?=###|\Z)',
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(report):
        severity = m.group(1).upper()
        title    = m.group(2).strip()
        body     = m.group(3)

        cve_m   = re.search(r'CVE-\d{4}-\d+', body)
        svc_m   = re.search(r'\*\*Service:\*\*\s*([^\n]+)', body, re.IGNORECASE)
        desc_m  = re.search(r'\*\*Description:\*\*\s*([^\n]+)', body, re.IGNORECASE)

        findings.append({
            "severity":    severity,
            "title":       title,
            "cve":         cve_m.group(0) if cve_m else None,
            "service":     svc_m.group(1).strip() if svc_m else None,
            "description": desc_m.group(1).strip() if desc_m else None,
        })
    return findings


# ── Public API ───────────────────────────────────────────────

def save_scan(target: str, report: str, report_path: Optional[Path] = None) -> int:
    """Parse and persist a completed scan. Returns the new scan id."""
    init_db()
    counts   = _parse_severity_counts(report)
    ports    = _parse_open_ports(report)
    services = _parse_services(report)
    findings = _parse_findings(report)

    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO scans
               (target, scanned_at, ports_open, services, crit, high, medium, low, report_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                target,
                datetime.now().isoformat(timespec="seconds"),
                ports,
                services,
                counts["CRITICAL"],
                counts["HIGH"],
                counts["MEDIUM"],
                counts["LOW"],
                str(report_path) if report_path else None,
            ),
        )
        scan_id = cur.lastrowid
        for f in findings:
            conn.execute(
                """INSERT INTO findings (scan_id, severity, title, cve, service, description)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (scan_id, f["severity"], f["title"], f["cve"], f["service"], f["description"]),
            )
    return scan_id


def get_previous_scans(target: str) -> list[sqlite3.Row]:
    """Return all past scans for a target, newest first."""
    init_db()
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM scans WHERE target = ? ORDER BY scanned_at DESC",
            (target,),
        ).fetchall()


def get_context(target: str) -> str:
    """
    Build a memory context string to prepend to the agent's first message.
    Returns empty string if no previous scans exist.
    """
    init_db()
    scans = get_previous_scans(target)
    if not scans:
        return ""

    lines = [
        f"## Memory: Previous Scans of {target}",
        f"This target has been scanned {len(scans)} time(s) before.\n",
    ]

    for scan in scans[:3]:  # show up to 3 most recent
        lines += [
            f"### Scan on {scan['scanned_at']}",
            f"- Open ports: {scan['ports_open'] or 'unknown'}",
            f"- Services: {scan['services'] or 'unknown'}",
            f"- Severity: CRIT={scan['crit']} HIGH={scan['high']} "
            f"MED={scan['medium']} LOW={scan['low']}",
        ]
        with _conn() as conn:
            findings = conn.execute(
                "SELECT severity, title, cve FROM findings WHERE scan_id = ? ORDER BY "
                "CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 "
                "WHEN 'MEDIUM' THEN 3 ELSE 4 END",
                (scan["id"],),
            ).fetchall()
        if findings:
            lines.append("- Findings:")
            for f in findings:
                cve_tag = f" ({f['cve']})" if f["cve"] else ""
                lines.append(f"    • [{f['severity']}] {f['title']}{cve_tag}")
        lines.append("")

    lines += [
        "Use this prior knowledge to:",
        "- Skip re-enumerating services already confirmed above",
        "- Focus on NEW findings or changes since the last scan",
        "- Cross-reference any new CVEs with previously known services",
        "---",
    ]
    return "\n".join(lines)


def list_scans(target: Optional[str] = None) -> list[sqlite3.Row]:
    """Return all scans, optionally filtered by target."""
    init_db()
    with _conn() as conn:
        if target:
            return conn.execute(
                "SELECT * FROM scans WHERE target = ? ORDER BY scanned_at DESC",
                (target,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM scans ORDER BY scanned_at DESC"
        ).fetchall()


def days_since_last_scan(target: str) -> Optional[float]:
    """Return days since the most recent scan of target, or None if never scanned."""
    scans = get_previous_scans(target)
    if not scans:
        return None
    last = datetime.fromisoformat(scans[0]["scanned_at"])
    return (datetime.now() - last).total_seconds() / 86400
