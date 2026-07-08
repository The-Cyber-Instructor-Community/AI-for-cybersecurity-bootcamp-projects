"""
Gobuster tool — directory/file enumeration against web targets.
"""
import subprocess
import re
import shutil
from pathlib import Path


# Small built-in wordlist so the tool works even without a system wordlist
BUILTIN_WORDLIST = [
    "admin", "login", "wp-admin", "phpmyadmin", "dashboard",
    "backup", "config", "test", "api", "uploads", "images",
    "css", "js", "includes", "cgi-bin", "server-status",
    "robots.txt", "sitemap.xml", ".htaccess", "index.php",
    "wp-login.php", "xmlrpc.php", "shell", "cmd", "console",
]

SYSTEM_WORDLISTS = [
    "/usr/share/wordlists/dirb/common.txt",          # Kali
    "/usr/local/share/wordlists/dirb/common.txt",    # Homebrew
    "/opt/homebrew/share/wordlists/dirb/common.txt", # Apple Silicon brew
]


def _get_wordlist(custom_wordlist: str | None) -> str:
    """Return path to best available wordlist, creating a temp one if needed."""
    if custom_wordlist and Path(custom_wordlist).exists():
        return custom_wordlist

    for wl in SYSTEM_WORDLISTS:
        if Path(wl).exists():
            return wl

    # Fall back to built-in minimal wordlist
    tmp = Path("/tmp/autoredteam_wordlist.txt")
    tmp.write_text("\n".join(BUILTIN_WORDLIST))
    return str(tmp)


def run_gobuster(
    target: str,
    port: int = 80,
    ssl: bool = False,
    wordlist: str | None = None,
    extensions: str = "php,html,txt,bak",
) -> dict:
    """
    Run Gobuster directory enumeration.

    Args:
        target:     IP or hostname
        port:       Web port (default 80)
        ssl:        Use HTTPS
        wordlist:   Path to wordlist file (uses built-in if not provided)
        extensions: Comma-separated file extensions to try

    Returns:
        dict with keys: target, port, found_paths, raw_output, error
    """
    if not shutil.which("gobuster"):
        return {"error": "gobuster not found — install with: brew install gobuster"}

    scheme = "https" if ssl else "http"
    url    = f"{scheme}://{target}:{port}"
    wl     = _get_wordlist(wordlist)

    cmd = [
        "gobuster", "dir",
        "-u", url,
        "-w", wl,
        "-x", extensions,
        "-t", "20",          # 20 threads
        "--timeout", "10s",
        "-q",                # quiet — only print findings
        "--no-error",
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
        return {"error": "Gobuster timed out after 120s", "target": target, "port": port}
    except Exception as e:
        return {"error": str(e), "target": target, "port": port}

    found_paths = []
    for line in raw.splitlines():
        # Lines look like: /admin (Status: 200) [Size: 1234]
        m = re.match(r"^(/\S+)\s+\(Status:\s*(\d+)\)", line.strip())
        if m:
            path, status = m.groups()
            found_paths.append({"path": path, "status": int(status)})

    return {
        "target":      target,
        "port":        port,
        "url":         url,
        "wordlist":    wl,
        "found_paths": found_paths,
        "path_count":  len(found_paths),
        "raw_output":  raw,
        "error":       None,
    }
