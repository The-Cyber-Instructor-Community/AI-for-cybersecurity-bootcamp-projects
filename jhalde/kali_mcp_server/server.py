"""
kali_mcp_server/server.py
──────────────────────────
AutoRedTeam Kali MCP Server — runs ON the Kali Linux VM.
Exposes all Kali pentest tools via:
  - MCP SSE transport at /sse  (for MCP clients)
  - Simple REST at /call       (for direct HTTP calls from the macOS agent)

Start on Kali:
    python3 server.py --host 0.0.0.0 --port 8765
"""

import argparse
import subprocess
import json
import os
import secrets
import shutil
from pathlib import Path

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp import types
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn


app = Server("kali-autoredteam")

# ── Auth token — set MCP_API_TOKEN in environment before starting ──
_API_TOKEN = os.environ.get("MCP_API_TOKEN", "")


def _check_auth(request: Request) -> bool:
    """Return True if the request carries a valid Bearer token."""
    if not _API_TOKEN:
        return True  # token not configured — warn at startup but don't block (dev mode)
    auth = request.headers.get("Authorization", "")
    return secrets.compare_digest(auth, f"Bearer {_API_TOKEN}")


def _available(binary: str) -> bool:
    return shutil.which(binary) is not None


def _run(cmd: list, timeout: int = 120) -> dict:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "stdout":     r.stdout,
            "stderr":     r.stderr,
            "returncode": r.returncode,
            "error":      None,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "", "returncode": -1,
                "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"stdout": "", "stderr": "", "returncode": -1, "error": str(e)}


ALLOWED = {
    "recon":           {"nmap", "masscan", "theHarvester", "dnsenum", "dnsrecon",
                        "whois", "fierce", "amass", "subfinder", "netdiscover",
                        "arp-scan", "ping", "traceroute", "host", "dig", "nslookup",
                        "enum4linux-ng", "enum4linux", "nbtscan"},
    "web_scan":        {"nikto", "gobuster", "dirb", "wfuzz", "sqlmap", "whatweb",
                        "wafw00f", "ffuf", "feroxbuster", "curl", "wget", "nuclei"},
    "smb_enum":        {"enum4linux-ng", "enum4linux", "smbmap", "smbclient",
                        "rpcclient", "nbtscan", "crackmapexec"},
    "exploit":         {"msfconsole", "searchsploit", "msfvenom"},
    "password_attack": {"hydra", "john", "hashcat", "medusa", "crunch", "cewl",
                        "patator", "ncrack"},
    "post_exploit":    {"shell", "linpeas.sh", "linenum.sh", "pspy",
                        "linux-exploit-suggester", "id", "whoami", "uname",
                        "cat", "ls", "ps", "netstat", "ss", "find"},
}


def _execute(category: str, tool: str, args: list, timeout: int) -> dict:
    """Core execution logic shared by REST and MCP handlers."""
    allowed = ALLOWED.get(category, set())
    if tool not in allowed:
        return {"error": f"Tool '{tool}' not allowed in '{category}'. Allowed: {sorted(allowed)}"}

    if not _available(tool) and tool != "shell":
        return {"error": f"'{tool}' not installed. Run: sudo apt install {tool}"}

    if tool == "msfconsole" and args:
        cmd = ["msfconsole", "-q", "-x", args[0] if len(args) == 1 else " ".join(args)]
    elif tool == "shell":
        cmd = ["/bin/bash", "-c", " ".join(args)]
    else:
        cmd = [tool] + [str(a) for a in args]

    result = _run(cmd, timeout=timeout)
    result["tool"]    = tool
    result["command"] = " ".join(cmd)
    return result


# ── REST /call endpoint ──────────────────────────────────────
# Simple direct HTTP API — no MCP session handshake needed.
# POST /call  {"category": "recon", "tool": "nmap", "args": [...], "timeout": 120}

async def handle_call(request: Request) -> JSONResponse:
    if not _check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        body     = await request.json()
        category = body.get("category", "")
        tool     = body.get("tool", "")
        args     = body.get("args", [])
        timeout  = body.get("timeout", 120)
        result   = _execute(category, tool, args, timeout)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "kali-autoredteam"})


# ── MCP tool definitions ─────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=category,
            description=f"Run {category} tools on Kali.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tool":    {"type": "string"},
                    "args":    {"type": "array", "items": {"type": "string"}},
                    "timeout": {"type": "integer"},
                },
                "required": ["tool", "args"],
            },
        )
        for category in ALLOWED
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    result = _execute(
        category=name,
        tool=arguments.get("tool", ""),
        args=arguments.get("args", []),
        timeout=arguments.get("timeout", 120),
    )
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


# ── Starlette app ─────────────────────────────────────────────

def create_app(mcp_server: Server) -> Starlette:
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_server.run(
                streams[0], streams[1],
                mcp_server.create_initialization_options(),
            )

    return Starlette(routes=[
        Route("/health",    endpoint=handle_health),
        Route("/call",      endpoint=handle_call,  methods=["POST"]),
        Route("/sse",       endpoint=handle_sse),
        Route("/messages/", endpoint=sse.handle_post_message, methods=["POST"]),
    ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kali MCP Server for AutoRedTeam")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()

    print(f"[*] Kali MCP Server starting on {args.host}:{args.port}")
    print(f"[*] REST endpoint: http://<kali-ip>:{args.port}/call")
    print(f"[*] MCP endpoint:  http://<kali-ip>:{args.port}/sse")
    if _API_TOKEN:
        print(f"[*] Auth: Bearer token configured (MCP_API_TOKEN)")
    else:
        print("[!] WARNING: MCP_API_TOKEN not set — server is unauthenticated!")
        print("[!]   Set it: export MCP_API_TOKEN=<your-secret> before starting")

    uvicorn.run(create_app(app), host=args.host, port=args.port)
