"""
VirusTotal reputation — HASH LOOKUP ONLY. We never upload files (leaks data +
tips off an attacker). 'Unknown to VT' is returned as inconclusive, not clean.

Needs VT_API_KEY (free tier: 4 lookups/min). Degrades gracefully if absent.
"""

from __future__ import annotations

import os
import requests

VT_URL = "https://www.virustotal.com/api/v3/files/{sha256}"


def vt_lookup(sha256: str) -> dict:
    key = os.environ.get("VT_API_KEY")
    if not key:
        return {"sha256": sha256, "status": "unavailable",
                "note": "VT_API_KEY not set — reputation unavailable (treat as inconclusive)"}
    if not sha256:
        return {"status": "error", "note": "no hash provided"}
    try:
        r = requests.get(VT_URL.format(sha256=sha256),
                         headers={"x-apikey": key}, timeout=20)
    except requests.RequestException as exc:
        return {"sha256": sha256, "status": "error", "note": str(exc)}

    if r.status_code == 404:
        return {"sha256": sha256, "status": "not_found",
                "note": "unknown to VT — inconclusive, NOT proof of benign"}
    if r.status_code == 429:
        return {"sha256": sha256, "status": "rate_limited"}
    if r.status_code != 200:
        return {"sha256": sha256, "status": "error", "http": r.status_code}

    stats = r.json().get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
    malicious = stats.get("malicious", 0)
    return {
        "sha256": sha256, "status": "found",
        "malicious": malicious, "suspicious": stats.get("suspicious", 0),
        "harmless": stats.get("harmless", 0), "undetected": stats.get("undetected", 0),
        "verdict": "malicious" if malicious > 0 else "clean",
    }
