"""
enum4linux tool — SMB/NetBIOS enumeration via enum4linux-ng.
Discovers users, shares, OS info, password policies, and null sessions.
"""
import subprocess
import json
import shutil
import tempfile
from pathlib import Path


ENUM4LINUX_BIN = "/Library/Frameworks/Python.framework/Versions/3.13/bin/enum4linux-ng"


def run_enum4linux(target: str) -> dict:
    """
    Run enum4linux-ng against target to enumerate SMB/NetBIOS info.

    Args:
        target: IP address (e.g. "192.168.56.101")

    Returns:
        dict with keys: target, users, shares, os_info, password_policy,
                        null_session, raw_output, error
    """
    binary = shutil.which("enum4linux-ng") or ENUM4LINUX_BIN

    if not shutil.which(binary) and not Path(binary).exists():
        return {"error": "enum4linux-ng not found — install with: pip install git+https://github.com/cddmp/enum4linux-ng"}

    # enum4linux-ng writes JSON to <outfile>.json; use a temp dir
    with tempfile.TemporaryDirectory() as tmpdir:
        out_base = str(Path(tmpdir) / "result")
        cmd = [
            binary,
            "-A",           # all simple enumeration
            "-oJ", out_base,
            target,
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
            return {"error": "enum4linux-ng timed out after 120s", "target": target}
        except Exception as e:
            return {"error": str(e), "target": target}

        # Load JSON output written by the tool
        json_path = Path(out_base + ".json")
        data: dict = {}
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text())
            except json.JSONDecodeError:
                pass

    # Parse structured data
    users:           list = []
    shares:          list = []
    os_info:         dict = {}
    password_policy: dict = {}
    null_session:    bool = False

    if data:
        # Users — stored under "users" key, value is a dict keyed by RID
        users_data = data.get("users", {})
        if isinstance(users_data, dict):
            for rid, uinfo in users_data.items():
                if isinstance(uinfo, dict):
                    users.append({
                        "username": uinfo.get("username", str(rid)),
                        "rid":      uinfo.get("rid", rid),
                        "comment":  uinfo.get("comment", ""),
                    })

        # Shares — dict keyed by share name
        shares_data = data.get("shares", {})
        if isinstance(shares_data, dict):
            for name, sinfo in shares_data.items():
                if isinstance(sinfo, dict):
                    shares.append({
                        "name":    name,
                        "type":    sinfo.get("type", ""),
                        "comment": sinfo.get("comment", ""),
                        "access":  sinfo.get("access", ""),
                    })

        os_info         = data.get("os_info", {}) or {}
        password_policy = data.get("password_policy", {}) or {}
        null_session    = bool(data.get("null_session", False))

    else:
        # Fall back to parsing terminal output if JSON file was not written
        for line in raw.splitlines():
            line_clean = line.strip()
            # Strip ANSI colour codes for matching
            import re
            plain = re.sub(r"\x1b\[[0-9;]*m", "", line_clean)
            if "null session" in plain.lower() and ("ok" in plain.lower() or "true" in plain.lower()):
                null_session = True
            if plain.startswith("[+]") and "username" in plain.lower():
                users.append({"username": plain, "rid": "", "comment": ""})

    return {
        "target":           target,
        "null_session":     null_session,
        "users":            users,
        "shares":           shares,
        "os_info":          os_info,
        "password_policy":  password_policy,
        "user_count":       len(users),
        "share_count":      len(shares),
        "raw_output":       raw,
        "error":            None,
    }
