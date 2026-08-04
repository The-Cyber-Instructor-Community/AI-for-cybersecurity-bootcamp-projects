"""
agent/kali_client.py
─────────────────────
HTTP client for the remote Kali MCP server.

Calls /call (simple REST) rather than the MCP SSE /messages/ endpoint,
which requires a session_id handshake that adds unnecessary complexity.

Falls back gracefully when Kali is unreachable.
"""

import json
import os
import socket
import urllib.parse
from typing import Optional

import httpx

import config

_KALI_URL_DEFAULT = getattr(config, "KALI_MCP_URL", "http://192.168.128.3:8765")
_reachable: Optional[bool] = None  # cached after first check


def _kali_base() -> str:
    import os
    url = os.environ.get("KALI_MCP_URL", _KALI_URL_DEFAULT)
    return url.rstrip("/")


def check_kali_reachable(timeout: float = 3.0) -> bool:
    """TCP socket check — True if the Kali MCP server port is open."""
    global _reachable
    if _reachable is not None:
        return _reachable
    try:
        parsed = urllib.parse.urlparse(_kali_base())
        host   = parsed.hostname
        port   = parsed.port or 8765
        sock   = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        _reachable = True
    except Exception:
        _reachable = False
    return _reachable


def _auth_headers() -> dict:
    """Return Authorization header if MCP_API_TOKEN is set."""
    token = os.environ.get("MCP_API_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def call_kali_tool(tool_category: str, tool: str, args: list,
                   timeout: int = 180) -> dict:
    """
    POST to /call on the Kali MCP server.

    Args:
        tool_category: one of recon, web_scan, smb_enum, exploit,
                       password_attack, post_exploit
        tool:          binary name (e.g. 'nmap', 'nikto', 'hydra')
        args:          argument list for the binary
        timeout:       seconds to wait for the command to finish

    Returns:
        dict with keys: stdout, stderr, returncode, error, tool, command
    """
    base = _kali_base()
    payload = {
        "category": tool_category,
        "tool":     tool,
        "args":     [str(a) for a in args],
        "timeout":  timeout,
    }
    try:
        r = httpx.post(
            f"{base}/call",
            json=payload,
            headers=_auth_headers(),
            timeout=timeout + 15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "stdout": "", "stderr": "", "returncode": -1}


def list_kali_tools() -> dict:
    """Return the health/status of the Kali MCP server."""
    base = _kali_base()
    try:
        r = httpx.get(f"{base}/health", timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}
