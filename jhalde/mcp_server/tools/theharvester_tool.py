"""
theHarvester tool — OSINT email/subdomain/host harvesting for domain targets.
Only useful when the target is a domain name, not an IP. Skipped for IPs.
"""
import subprocess
import json
import re
import shutil
import tempfile
from pathlib import Path


HARVESTER_BIN = "/usr/local/bin/theHarvester"


def run_theharvester(domain: str, sources: str = "bing,duckduckgo,crtsh") -> dict:
    """
    Run theHarvester to collect OSINT on a domain.

    Args:
        domain:  Domain name to harvest (e.g. "example.com")
                 Returns a no-op result if an IP is passed.
        sources: Comma-separated data sources (default: bing,duckduckgo,crtsh)

    Returns:
        dict with keys: domain, emails, hosts, ips, asns, json_file, error
    """
    # Skip IP addresses — theHarvester is domain-only
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", domain):
        return {
            "domain":  domain,
            "skipped": True,
            "reason":  "theHarvester is for domain targets only — skipping IP address",
            "emails":  [],
            "hosts":   [],
            "ips":     [],
            "error":   None,
        }

    binary = shutil.which("theHarvester") or HARVESTER_BIN
    if not Path(binary).exists() and not shutil.which(binary):
        return {"error": "theHarvester not found — install with: brew install theharvester"}

    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = str(Path(tmpdir) / "harvest")
        cmd = [
            binary,
            "-d", domain,
            "-b", sources,
            "-f", out_file,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            raw = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return {"error": "theHarvester timed out after 120s", "domain": domain}
        except Exception as e:
            return {"error": str(e), "domain": domain}

        # Parse JSON output if available
        json_path = Path(out_file + ".json")
        emails, hosts, ips, asns = [], [], [], []

        if json_path.exists():
            try:
                data = json.loads(json_path.read_text())
                emails = data.get("emails", [])
                hosts  = data.get("hosts", [])
                ips    = data.get("ips", [])
                asns   = data.get("asns", [])
            except (json.JSONDecodeError, Exception):
                pass

        # Fallback: parse terminal output
        if not emails and not hosts:
            emails, hosts, ips = _parse_text_output(raw)

    return {
        "domain":      domain,
        "sources_used": sources,
        "emails":      list(set(emails)),
        "hosts":       list(set(hosts)),
        "ips":         list(set(ips)),
        "asns":        list(set(asns)),
        "email_count": len(set(emails)),
        "host_count":  len(set(hosts)),
        "skipped":     False,
        "error":       None,
    }


def _parse_text_output(raw: str) -> tuple:
    """Extract emails, hosts, and IPs from theHarvester terminal output."""
    emails, hosts, ips = [], [], []
    email_pattern = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    ip_pattern    = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")

    in_emails = in_hosts = False
    for line in raw.splitlines():
        line = line.strip()
        if "Emails found" in line or "[*] Emails" in line:
            in_emails = True; in_hosts = False; continue
        if "Hosts found" in line or "[*] Hosts" in line or "IPs found" in line:
            in_hosts = True; in_emails = False; continue
        if line.startswith("---") or not line:
            continue

        if in_emails:
            for m in email_pattern.findall(line):
                emails.append(m)
        elif in_hosts:
            if "." in line:
                hosts.append(line)
            for ip in ip_pattern.findall(line):
                ips.append(ip)

        # Always capture loose emails
        for m in email_pattern.findall(line):
            if m not in emails:
                emails.append(m)

    return emails, hosts, ips
