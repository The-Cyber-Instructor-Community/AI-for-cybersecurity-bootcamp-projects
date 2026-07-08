"""
searchsploit tool — offline ExploitDB lookup for service versions.
Returns known public exploits via searchsploit -j (JSON output).
"""
import subprocess
import json
import shutil


def run_searchsploit(query: str) -> dict:
    """
    Search ExploitDB for exploits matching a service/version.

    Args:
        query: Search string, e.g. "vsftpd 2.3.4" or "samba 3.0.20"

    Returns:
        dict with keys: query, exploits (list), exploit_count, error
    """
    if not shutil.which("searchsploit"):
        return {"error": "searchsploit not found — install with: brew install exploitdb"}

    cmd = ["searchsploit", "-j", query]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"error": "searchsploit timed out", "query": query}
    except Exception as e:
        return {"error": str(e), "query": query}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "Failed to parse searchsploit JSON output", "query": query, "raw": result.stdout[:500]}

    exploits = []
    for entry in data.get("RESULTS_EXPLOIT", []):
        exploits.append({
            "title":    entry.get("Title", ""),
            "edb_id":   entry.get("EDB-ID", ""),
            "type":     entry.get("Type", ""),
            "platform": entry.get("Platform", ""),
            "cves":     entry.get("Codes", ""),
            "path":     entry.get("Path", "").replace(data.get("DB_PATH_EXPLOIT", ""), "").lstrip("/"),
            "edb_url":  f"https://www.exploit-db.com/exploits/{entry.get('EDB-ID', '')}",
            "verified": entry.get("Verified", "0") == "1",
        })

    return {
        "query":         query,
        "exploits":      exploits,
        "exploit_count": len(exploits),
        "error":         None,
    }
