# AutoRedTeam — AI-Powered Autonomous Penetration Testing Agent

> An end-to-end AI security agent that autonomously scans a target, identifies vulnerabilities using RAG over 2000+ CVEs + 697 MITRE ATT&CK techniques, and generates a professional pentest report — complete with remediation playbooks and Metasploit exploit references.

---

## Demo

```
$ python3 -m agent.agent 127.0.0.1 --ports 2121,2222,8080,44500,33060,18180

╭─────────────────────────────────────────────────────────╮
│ AutoRedTeam Agent                                       │
│ Target: 127.0.0.1  |  Ports: 2121,2222,8080,44500,...  │
╰─────────────────────────────────────────────────────────╯

[Tool 1]  whois_lookup       → private RFC-1918 address
[Tool 2]  dns_recon          → PTR: localhost
[Tool 3]  theharvester_scan  → skipped (IP target)
[Tool 4]  nmap_scan          → vsftpd 2.3.4, OpenSSH 4.7, Apache 2.2.8, Samba 3.X
[Tool 5]  nikto_scan         → 8 web findings on port 8080
[Tool 6]  gobuster_scan      → /phpmyadmin, /dvwa discovered
[Tool 7]  enum4linux_scan    → 35 users, null session, world-writable shares
[Tool 8]  searchsploit_lookup → EDB-17491 vsftpd backdoor (verified)
[Tool 9]  query_cve_database → CVE-2011-2523 CVSS 9.8, CVE-2007-2447 CVSS 10.0
[Tool 10] analyze_cve_with_model → expert analysis from fine-tuned Llama 3.1 8B
...
[Tool 36] query_attack_techniques → T1190, T1021.002, T1078

✓ Agent completed — 36 tool calls
✓ Report saved: reports/report_127_0_0_1_YYYYMMDD.md + .html
```

**Findings on Metasploitable2:** 3 CRITICAL · 5 HIGH · 1 MEDIUM  
**Root shells confirmed:** vsftpd 2.3.4 backdoor + Samba 3.0.20 RCE

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     AutoRedTeam Agent                        │
│                (Claude Sonnet + Tool Use API)                 │
└──────┬──────────────┬──────────────┬──────────────┬──────────┘
       │              │              │              │
┌──────▼──────┐ ┌─────▼──────┐ ┌────▼────────┐ ┌──▼──────────┐
│ Local Tools │ │ RAG Layer  │ │ Fine-tuned  │ │ Kali MCP   │
│ ─────────── │ │ ────────── │ │ LLM         │ │ Server     │
│ nmap        │ │ ChromaDB   │ │ ─────────── │ │ ────────── │
│ nikto       │ │ 2000+ CVEs │ │ Llama 3.1 8B│ │ nmap/masscan│
│ gobuster    │ │ 697 TTPs   │ │ QLoRA adapt │ │ hydra/john  │
│ enum4linux  │ │            │ │ CVE analysis│ │ msfconsole  │
│ searchsploit│ │            │ │             │ │ sqlmap/ffuf │
│ whois/dns   │ └─────┬──────┘ └────┬────────┘ └──┬──────────┘
│ theHarvester│       │              │              │
└──────┬──────┘       └──────────────▼──────────────┘
       │                      ┌───────────────┐
       └─────────────────────▶│  Report Gen   │
                              │ ─────────────  │
                              │  Markdown      │
                              │  HTML Dashboard│
                              │  Remediation   │
                              │  ATT&CK Mapping│
                              └───────────────┘
```

---

## Features

| Feature | Detail |
|---------|--------|
| **Autonomous 5-phase workflow** | Passive Recon → Active Scan → Intelligence → Exploitation → Report |
| **19 tools** | whois, DNS, theHarvester, nmap, nikto, gobuster, enum4linux, searchsploit, Metasploit RPC, Kali MCP, CVE RAG, ATT&CK RAG, fine-tuned model |
| **RAG knowledge base** | 2000+ high-severity CVEs (NVD) + 697 ATT&CK techniques in ChromaDB |
| **Fine-tuned Llama 3.1 8B** | QLoRA-trained on 500 expert CVE analyses; loss 1.92→0.73 |
| **Kali MCP server** | Remote tool execution over HTTP — runs any Kali tool from the agent |
| **Passive recon** | WHOIS, DNS (PTR/A/MX/NS/TXT/zone transfer/subdomain brute-force), OSINT |
| **Metasploit RPC** | Direct exploit execution via pymetasploit3 + msfrpcd |
| **Professional reports** | Markdown + HTML dashboard with severity charts |
| **Remediation playbooks** | Exact fix commands and verification steps per finding |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent Orchestration | Claude Sonnet 4.6 (Anthropic) + Tool Use API |
| Fine-tuning | Llama 3.1 8B + Unsloth QLoRA (Google Colab T4) |
| RAG | ChromaDB + sentence-transformers (all-MiniLM-L6-v2) |
| CVE Data | NVD 2.0 API — 2000+ CVEs (CVSS ≥ 7.0) |
| ATT&CK Data | MITRE ATT&CK Enterprise STIX — 697 techniques |
| Pentest Tools | nmap · nikto · gobuster · enum4linux-ng · searchsploit · Metasploit |
| Remote Tools | Kali Linux MCP server (HTTP REST + SSE transport) |
| Target | Metasploitable2 (UTM/VirtualBox) |

---

## Quickstart

### ⚠️ VPN Warning

**Disconnect your VPN before running the agent or starting UTM VMs.**

VPN clients modify macOS packet filter (`pf`) rules and break UTM's virtual bridge networking (`bridge100`/`bridge101`). Symptoms include: 100% ping loss to VMs, SSH timeouts, Anthropic API disconnections mid-run, and DHCP failures on virtual interfaces.

---

### 1. Prerequisites

**macOS (Homebrew):**
```bash
brew install nmap nikto gobuster samba exploitdb
pip install git+https://github.com/cddmp/enum4linux-ng
```

**Python 3.11+** and an [Anthropic API key](https://console.anthropic.com).  
**NVD API key** (free) at [nvd.nist.gov](https://nvd.nist.gov/developers/request-an-api-key).

### 2. Install

```bash
git clone <repo>
cd autoredteam
pip install -r requirements.txt
```

Create `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
NVD_API_KEY=your-nvd-key
KALI_MCP_URL=http://localhost:8765   # optional — see Kali MCP section
```

### 3. Build the knowledge base

```bash
python3 -m rag.ingest_cve      # ~5 min — ingests 2000+ CVEs from NVD
python3 -m rag.ingest_attack   # ~2 min — ingests 697 ATT&CK techniques
python3 test_rag.py            # validate
```

### 4. Set up the target (Metasploitable2 in UTM)

In UTM, create a QEMU x86_64 VM using the Metasploitable2 VMDK, set network to **Emulated VLAN**, and add these port forwards:

| Guest Port | Host Port | Service |
|-----------|-----------|---------|
| 21 | 2121 | FTP (vsftpd 2.3.4) |
| 22 | 2222 | SSH |
| 80 | 8080 | HTTP (Apache 2.2.8) |
| 445 | 44500 | SMB (Samba 3.0.20) |
| 3306 | 33060 | MySQL |
| 8180 | 18180 | Tomcat |

Then run the agent against `127.0.0.1` with the forwarded ports.

### 5. Run the agent

```bash
# Quick scan (forwarded ports)
python3 -m agent.agent 127.0.0.1 --ports 2121,2222,8080,44500,33060,18180

# Full port range (direct network access)
python3 -m agent.agent 192.168.128.2 --ports 1-65535
```

Reports are saved to `reports/` as `.md` and `.html`.

---

## Kali MCP Server (optional)

Run any Kali Linux tool remotely from the agent via HTTP:

```bash
# On Kali VM:
cd ~/kali_mcp_server
python3 server.py --host 0.0.0.0 --port 8765

# Test from macOS:
curl http://<kali-ip>:8765/health
curl -X POST http://<kali-ip>:8765/call \
  -H "Content-Type: application/json" \
  -d '{"category":"recon","tool":"nmap","args":["-sV","192.168.128.2"]}'
```

Set `KALI_MCP_URL` in `.env` to your Kali IP. The agent automatically prefers Kali tools when reachable and falls back to local tools when not.

**Available tool categories:** `recon` · `web_scan` · `smb_enum` · `exploit` · `password_attack` · `post_exploit`

---

## Fine-tuning (optional)

```bash
# Generate training dataset (500 CVE analyses via Claude Haiku)
python3 -m finetune.generate_dataset --count 500

# Train on Google Colab (T4 GPU, ~45 min)
# Open finetune/autoredteam_colab.ipynb → Runtime → T4 GPU → Run all
```

Training results: **loss 1.92 → 0.73** over 3 epochs, 41.9M trainable parameters.

If no fine-tuned model is present, the agent automatically falls back to Claude Haiku for CVE analysis.

---

## Project Structure

```
autoredteam/
├── agent/                      # Agent orchestration
│   ├── agent.py                # Main loop (5-phase workflow, 40-tool limit)
│   ├── tools.py                # 19 tool definitions + executor
│   ├── kali_client.py          # Kali MCP HTTP client
│   ├── model_analyzer.py       # Fine-tuned model / Haiku fallback
│   ├── report.py               # Markdown report saving
│   ├── html_report.py          # HTML dashboard generation
│   ├── remediation.py          # Remediation playbook enhancer
│   └── exploits.py             # Metasploit module suggestions
├── mcp_server/                 # Local MCP tool implementations
│   ├── server.py               # MCP SSE server
│   └── tools/
│       ├── nmap_tool.py
│       ├── nikto_tool.py
│       ├── gobuster_tool.py
│       ├── enum4linux_tool.py
│       ├── searchsploit_tool.py
│       ├── metasploit_tool.py  # pymetasploit3 RPC wrapper
│       ├── whois_tool.py
│       ├── dns_recon_tool.py
│       └── theharvester_tool.py
├── kali_mcp_server/            # Remote Kali MCP server
│   ├── server.py               # REST /call + MCP SSE endpoints
│   ├── requirements.txt
│   └── setup.sh                # Kali setup script
├── rag/                        # RAG knowledge base
│   ├── ingest_cve.py           # NVD CVE ingestion
│   ├── ingest_attack.py        # MITRE ATT&CK ingestion
│   └── query.py                # Query interface
├── finetune/                   # Fine-tuning pipeline
│   ├── generate_dataset.py     # Synthetic training data
│   └── autoredteam_colab.ipynb # Colab training notebook
├── scripts/
│   └── start_msfrpcd.sh        # Start Metasploit RPC daemon
├── reports/                    # Generated pentest reports
├── chroma_db/                  # Vector database (auto-created)
├── config.py                   # Central configuration
└── requirements.txt
```

---

## Extending the Agent

**Add a new tool:**
1. Create `mcp_server/tools/your_tool.py` with a `run_your_tool()` function
2. Add a tool definition to `TOOL_DEFINITIONS` in `agent/tools.py`
3. Add an `elif name == "your_tool"` branch in `execute_tool()`
4. Reference it in the system prompt in `agent/agent.py`

**Add more CVEs:**  
Edit `config.py` → increase `NVD_MAX_CVE` → re-run `python3 -m rag.ingest_cve`

**Add Kali tools:**  
Edit `ALLOWED` dict in `kali_mcp_server/server.py` to whitelist new binaries per category.

---

## Future Enhancements

| Enhancement | Description |
|-------------|-------------|
| **Multi-target scanning** | Accept a CIDR range and scan all hosts in parallel |
| **CVE-to-PoC mapping** | Auto-link CVEs to GitHub PoC repos via `poc-in-github` API |
| **Continuous monitoring** | Schedule recurring scans and alert on new findings via Slack/email |
| **Custom wordlists** | Auto-generate target-specific gobuster wordlists from theHarvester OSINT |
| **Cloud targets** | Add AWS/Azure/GCP enumeration tools (boto3, az cli, gcloud) |
| **LLM upgrade** | Swap Llama 3.1 8B for a larger model or fine-tune on more CVE pairs |
| **Vector DB growth** | Expand to 50,000 CVEs (change `NVD_MAX_CVE` in config.py) |
| **Nuclei integration** | Add `nuclei` as a Kali MCP tool for template-based vulnerability scanning |
| **Web dashboard** | Replace HTML report with a live React dashboard showing scan progress |
| **CI/CD integration** | GitHub Action that runs a lightweight scan on each PR against a staging target |
| **Agentic memory** | Persist findings across scans so the agent learns what changed over time |

---

## Security Rules

- **Never commit `.env`** — API keys must stay local
- **Agent suggests exploits, never executes them autonomously**
- **Only scan systems you own or have written permission to test**

---

## Disclaimer

AutoRedTeam is built for **authorised security testing and education only**. The exploit suggestions reference public Metasploit modules — they are never executed automatically. Unauthorized use against systems you do not own is illegal.

---

Built as an AI cybersecurity capstone — combining RAG, fine-tuning, MCP, and autonomous agents across 11 days.
