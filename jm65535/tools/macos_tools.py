"""
macOS endpoint investigation primitives (read-only enrichment).

The monitored endpoint is the host Mac, so these run locally via subprocess. For
a remote endpoint the same functions would run over SSH (tools/execution.py has
the SSH primitive). All functions are safe/read-only and return plain dicts.
"""

from __future__ import annotations

import hashlib
import plistlib
import subprocess
from pathlib import Path

SUSPICIOUS_DIRS = ("/tmp/", "/private/tmp/", "/var/tmp/", "/Users/Shared/")


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def read_plist(path: str) -> dict:
    """Parse a LaunchAgent/Daemon plist and surface the interesting fields."""
    p = Path(path)
    if not p.exists():
        return {"exists": False, "path": path}
    try:
        data = plistlib.loads(p.read_bytes())
    except Exception as exc:
        return {"exists": True, "path": path, "parse_error": str(exc)}
    args = data.get("ProgramArguments") or ([data["Program"]] if data.get("Program") else [])
    program = args[0] if args else data.get("Program")
    return {
        "exists": True,
        "path": path,
        "label": data.get("Label"),
        "program": program,
        "program_arguments": args,
        "run_at_load": bool(data.get("RunAtLoad", False)),
        "keep_alive": bool(data.get("KeepAlive", False)),
        "raw_keys": list(data.keys()),
    }


def read_text_file(path: str, max_bytes: int = 8000) -> dict:
    """Read a text file (e.g. a shell startup file) so the agent can inspect it."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {"path": path, "exists": False}
    try:
        content = p.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
    except Exception as exc:
        return {"path": path, "exists": True, "error": str(exc)}
    return {"path": path, "exists": True, "content": content, "lines": content.count("\n") + 1}


def sha256_file(path: str) -> dict:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {"path": path, "exists": False}
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return {"path": path, "exists": True, "sha256": h.hexdigest()}


def check_signature(path: str) -> dict:
    """Code-signing status of a binary/bundle via codesign + Gatekeeper (spctl)."""
    p = Path(path)
    if not p.exists():
        return {"path": path, "exists": False, "verdict": "missing"}

    rc, out, err = _run(["codesign", "-dv", "--verbose=4", str(path)])
    cs = out + "\n" + err  # codesign writes details to stderr
    authorities = [ln.split("=", 1)[1] for ln in cs.splitlines() if ln.startswith("Authority=")]
    signed = rc == 0
    apple = any("Apple" in a for a in authorities)
    dev_id = any("Developer ID" in a for a in authorities)

    grc, gout, gerr = _run(["spctl", "-a", "-vv", str(path)])
    gatekeeper = (gout + gerr).strip()

    if not signed:
        verdict = "unsigned"
    elif apple:
        verdict = "apple_signed"
    elif dev_id:
        verdict = "developer_id_signed"
    else:
        verdict = "adhoc_or_unknown_signer"

    return {
        "path": path, "exists": True, "signed": signed, "verdict": verdict,
        "authorities": authorities[:3], "gatekeeper": gatekeeper[:200],
    }


def path_reputation(path: str) -> dict:
    """Cheap heuristic on where a binary lives."""
    low = (path or "").lower()
    hits = [d for d in SUSPICIOUS_DIRS if d in low]
    name = Path(path).name if path else ""
    hidden = name.startswith(".")
    return {
        "path": path,
        "suspicious_location": bool(hits) or hidden,
        "matched": hits + (["hidden_file"] if hidden else []),
    }


def get_process_info(name_or_pid: str) -> dict:
    """Parent process + command line for a running process (by name or PID)."""
    if str(name_or_pid).isdigit():
        rc, out, _ = _run(["ps", "-o", "pid=,ppid=,user=,comm=,args=", "-p", str(name_or_pid)])
    else:
        rc, out, _ = _run(["pgrep", "-l", str(name_or_pid)])
        if rc != 0 or not out:
            return {"query": name_or_pid, "running": False}
        pid = out.split()[0]
        rc, out, _ = _run(["ps", "-o", "pid=,ppid=,user=,comm=,args=", "-p", pid])
    if rc != 0 or not out:
        return {"query": name_or_pid, "running": False}
    fields = out.split(None, 4)
    info = {"query": name_or_pid, "running": True, "pid": fields[0], "ppid": fields[1],
            "user": fields[2], "comm": fields[3], "args": fields[4] if len(fields) > 4 else ""}
    prc, pout, _ = _run(["ps", "-o", "comm=", "-p", info["ppid"]])
    info["parent_comm"] = pout if prc == 0 else "?"
    return info


def get_network_connections(pid: str) -> dict:
    """Established network connections for a PID via lsof."""
    if not str(pid).isdigit():
        return {"pid": pid, "error": "pid must be numeric"}
    rc, out, _ = _run(["lsof", "-nP", "-p", str(pid), "-i"])
    conns = [ln for ln in out.splitlines() if "->" in ln or "ESTABLISHED" in ln]
    return {"pid": pid, "connections": conns[:20], "count": len(conns)}
