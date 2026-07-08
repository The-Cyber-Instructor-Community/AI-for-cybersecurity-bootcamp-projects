"""
whois tool — passive domain/IP registration lookup.
Works for both IP addresses (ASN, netblock owner) and domain names.
"""
import subprocess
import shutil
import re


def run_whois(target: str) -> dict:
    """
    Run whois lookup on an IP address or domain.

    Args:
        target: IP address or domain name

    Returns:
        dict with keys: target, registrar, org, country, netblock,
                        abuse_contact, creation_date, raw_output, error
    """
    if not shutil.which("whois"):
        return {"error": "whois not found"}

    try:
        result = subprocess.run(
            ["whois", target],
            capture_output=True,
            text=True,
            timeout=30,
        )
        raw = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {"error": "whois timed out", "target": target}
    except Exception as e:
        return {"error": str(e), "target": target}

    return {
        "target":        target,
        "org":           _extract(raw, r"(?:OrgName|org-name|owner):\s*(.+)"),
        "registrar":     _extract(raw, r"Registrar:\s*(.+)"),
        "country":       _extract(raw, r"(?:Country|country):\s*(.+)"),
        "netblock":      _extract(raw, r"(?:CIDR|inetnum|NetRange):\s*(.+)"),
        "abuse_contact": _extract(raw, r"(?:OrgAbuseEmail|abuse-mailbox):\s*(.+)"),
        "creation_date": _extract(raw, r"(?:RegDate|created|Creation Date):\s*(.+)"),
        "asn":           _extract(raw, r"(?:OriginAS|ASNumber|origin):\s*(.+)"),
        "raw_output":    raw,
        "error":         None,
    }


def _extract(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else ""
