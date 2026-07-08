"""
Nikto tool — web vulnerability scanner, returns structured findings.
"""
import subprocess
import re
import shutil


def run_nikto(target: str, port: int = 80, ssl: bool = False) -> dict:
    """
    Run Nikto web vulnerability scan.

    Args:
        target:  IP or hostname (e.g. "192.168.56.101")
        port:    Web port to scan (default 80)
        ssl:     Use HTTPS (default False)

    Returns:
        dict with keys: target, port, findings, raw_output, error
    """
    if not shutil.which("nikto"):
        return {"error": "nikto not found — install with: brew install nikto"}

    scheme = "https" if ssl else "http"
    host   = f"{scheme}://{target}:{port}"

    cmd = [
        "nikto",
        "-h", host,
        "-nointeractive",
        "-Format", "txt",
        "-timeout", "15",
        "-maxtime", "180s",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=200,
        )
        raw = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {"error": "Nikto scan timed out after 120s", "target": target, "port": port}
    except Exception as e:
        return {"error": str(e), "target": target, "port": port}

    findings = []
    for line in raw.splitlines():
        line = line.strip()
        # Nikto findings start with +
        if line.startswith("+ ") and ":" in line:
            findings.append(line[2:])  # strip the "+ " prefix

    return {
        "target":   target,
        "port":     port,
        "ssl":      ssl,
        "findings": findings,
        "finding_count": len(findings),
        "raw_output": raw,
        "error":    None,
    }
