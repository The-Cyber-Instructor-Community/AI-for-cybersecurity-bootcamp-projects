"""
mcp_server/server.py
─────────────────────
AutoRedTeam MCP Server — exposes nmap, nikto, gobuster, and enum4linux
as tools that the agent can call via the MCP protocol.

Run:
    python3 -m mcp_server.server

The server communicates over stdio (standard MCP transport).
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from mcp_server.tools.nmap_tool import run_nmap
from mcp_server.tools.nikto_tool import run_nikto
from mcp_server.tools.gobuster_tool import run_gobuster
from mcp_server.tools.enum4linux_tool import run_enum4linux
from mcp_server.tools.searchsploit_tool import run_searchsploit

app = Server("autoredteam")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="nmap_scan",
            description=(
                "Run an nmap service/version scan against a target IP. "
                "Returns open ports and detected service versions. "
                "Use this first to discover the attack surface."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Target IP address (e.g. '192.168.56.101')",
                    },
                    "ports": {
                        "type": "string",
                        "description": "Port range to scan (default '1-1000')",
                        "default": "1-1000",
                    },
                },
                "required": ["target"],
            },
        ),
        types.Tool(
            name="nikto_scan",
            description=(
                "Run a Nikto web vulnerability scan against a target. "
                "Identifies outdated software, misconfigurations, and known web vulnerabilities. "
                "Use after nmap confirms HTTP/HTTPS is open."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Target IP address",
                    },
                    "port": {
                        "type": "integer",
                        "description": "Web port to scan (default 80)",
                        "default": 80,
                    },
                    "ssl": {
                        "type": "boolean",
                        "description": "Use HTTPS (default false)",
                        "default": False,
                    },
                },
                "required": ["target"],
            },
        ),
        types.Tool(
            name="gobuster_scan",
            description=(
                "Run Gobuster directory enumeration against a web target. "
                "Discovers hidden paths, admin panels, backup files, and exposed config. "
                "Use after Nikto to find attack surface not visible from the homepage."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Target IP address",
                    },
                    "port": {
                        "type": "integer",
                        "description": "Web port (default 80)",
                        "default": 80,
                    },
                    "ssl": {
                        "type": "boolean",
                        "description": "Use HTTPS (default false)",
                        "default": False,
                    },
                    "extensions": {
                        "type": "string",
                        "description": "File extensions to check (default 'php,html,txt,bak')",
                        "default": "php,html,txt,bak",
                    },
                },
                "required": ["target"],
            },
        ),
        types.Tool(
            name="enum4linux_scan",
            description=(
                "Run enum4linux-ng SMB/NetBIOS enumeration against a target. "
                "Discovers user accounts, shares, OS info, password policy, and null session status. "
                "Use when nmap finds port 139 or 445 open."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Target IP address (e.g. '192.168.128.2')",
                    },
                },
                "required": ["target"],
            },
        ),
        types.Tool(
            name="searchsploit_lookup",
            description=(
                "Search the local ExploitDB database for public exploits matching a service or version. "
                "Use after nmap to discover known public exploits for found services."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Service and version to search (e.g. 'vsftpd 2.3.4')",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "nmap_scan":
        result = run_nmap(
            target=arguments["target"],
            ports=arguments.get("ports", "1-1000"),
        )
    elif name == "nikto_scan":
        result = run_nikto(
            target=arguments["target"],
            port=arguments.get("port", 80),
            ssl=arguments.get("ssl", False),
        )
    elif name == "gobuster_scan":
        result = run_gobuster(
            target=arguments["target"],
            port=arguments.get("port", 80),
            ssl=arguments.get("ssl", False),
            extensions=arguments.get("extensions", "php,html,txt,bak"),
        )
    elif name == "enum4linux_scan":
        result = run_enum4linux(target=arguments["target"])
    elif name == "searchsploit_lookup":
        result = run_searchsploit(query=arguments["query"])
    else:
        result = {"error": f"Unknown tool: {name}"}

    # Strip raw_output from the result to keep context concise for the agent
    result.pop("raw_output", None)

    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
