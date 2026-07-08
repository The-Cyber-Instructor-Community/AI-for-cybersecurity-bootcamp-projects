# AutoRedTeam — Day-by-Day Quickstart

## Day 1 — RAG Pipeline

### 1. Create & activate a virtual environment
```bash
cd autoredteam
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. (Recommended) Get a free NVD API key
Takes 2 minutes. Without it, ingestion is rate-limited to ~3 CVEs/min.
→ https://nvd.nist.gov/developers/request-an-api-key

Then set it:
```bash
export NVD_API_KEY="your-key-here"
# Or create a .env file:  echo NVD_API_KEY=your-key >> .env
```

### 3. Ingest CVE data (High + Critical CVEs)
```bash
python -m rag.ingest_cve
```
Pulls ~2000 HIGH/CRITICAL CVEs from NVD. Takes ~5 min with API key.

### 4. Ingest MITRE ATT&CK techniques
```bash
python -m rag.ingest_attack
```
Downloads the full ATT&CK Enterprise STIX bundle (~697 techniques).

### 5. Validate your RAG pipeline
```bash
python test_rag.py
```
Runs 4 test queries against Metasploitable2-style services. All 4 should return results — that's Day 1 done ✓

---

## Day 2 — Fine-tune Llama 3.1 8B (Google Colab)

### 1. Generate training dataset
```bash
python -m finetune.generate_dataset --count 500
```
Uses Claude Haiku to generate 500 expert CVE analysis pairs. Output: `data/finetune_dataset.jsonl`

### 2. Train on Colab (T4 GPU, ~45 min)
1. Open `finetune/autoredteam_colab.ipynb` in Google Colab
2. Runtime → Change runtime type → **T4 GPU**
3. Upload `data/finetune_dataset.jsonl` when prompted
4. Run all cells

Training results: **loss 1.92 → 0.73** over 3 epochs, 41.9M trainable parameters.

### 3. Download the model
After training, download the `autoredteam-llama/` folder from Colab and place it in your project root.

> If no fine-tuned model is present, the agent automatically falls back to Claude Haiku for CVE analysis.

---

## Day 3 — Build the Agent

### 1. Set your Anthropic API key
```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
```

### 2. Install pentest tools (macOS)
```bash
brew install nmap nikto gobuster samba exploitdb
pip install git+https://github.com/cddmp/enum4linux-ng
```

### 3. Run a quick test
```bash
python3 -m agent.agent 127.0.0.1 --ports 22,80,443
```
The agent will use nmap, whois, DNS recon, and CVE lookup — 19 tools total.

---

## Day 4 — Set Up Metasploitable2 Target (UTM)

### 1. Download Metasploitable2
→ https://sourceforge.net/projects/metasploitable/

### 2. Create a UTM VM (Apple Silicon)
- New VM → Emulate → Other → x86_64
- Import the `.vmdk` file as the drive
- Set network to **Emulated VLAN**

### 3. Add port forwards in UTM

| Guest Port | Host Port | Service |
|-----------|-----------|---------|
| 21 | 2121 | FTP (vsftpd 2.3.4) |
| 22 | 2222 | SSH |
| 80 | 8080 | HTTP (Apache 2.2.8) |
| 445 | 44500 | SMB (Samba 3.0.20) |
| 3306 | 33060 | MySQL |
| 8180 | 18180 | Tomcat |

Default creds: `msfadmin / msfadmin`

### 4. Run agent against target
```bash
python3 -m agent.agent 127.0.0.1 --ports 2121,2222,8080,44500,33060,18180
```

---

## Day 5 — Metasploit RPC Integration

### 1. Start Metasploit RPC daemon
```bash
bash scripts/start_msfrpcd.sh
```

### 2. Test the connection
```bash
python3 -c "from mcp_server.tools.metasploit_tool import test_msf_connection; test_msf_connection()"
```

The agent will now use Metasploit to suggest and stage exploits (vsftpd backdoor, Samba usermap, etc.).

---

## Day 6-7 — Kali MCP Server

Run any Kali Linux tool remotely from the macOS agent via HTTP.

### 1. Set up a Kali Linux VM (UTM, Emulated VLAN)
Forward Kali SSH: Guest 22 → Host 2223

### 2. Install the MCP server on Kali
```bash
scp -P 2223 -r kali_mcp_server/ kali@127.0.0.1:~/
ssh -p 2223 kali@127.0.0.1 "cd ~/kali_mcp_server && bash setup.sh"
```

### 3. Start the server on Kali
```bash
ssh -p 2223 kali@127.0.0.1 "cd ~/kali_mcp_server && python3 server.py --host 0.0.0.0 --port 8765"
```

### 4. Point the agent at Kali
```bash
echo "KALI_MCP_URL=http://127.0.0.1:8765" >> .env
```
Forward Kali port 8765: Guest 8765 → Host 8765

### 5. Test from macOS
```bash
curl http://127.0.0.1:8765/health
curl -X POST http://127.0.0.1:8765/call \
  -H "Content-Type: application/json" \
  -d '{"category":"recon","tool":"nmap","args":["-sV","127.0.0.1"]}'
```

The agent automatically prefers Kali tools when reachable and falls back to local tools when not.

---

## Day 8 — Final Run & Report

### 1. Disconnect VPN
VPN modifies macOS `pf` rules and breaks UTM networking. Disconnect before running.

### 2. Run the full agent
```bash
python3 -m agent.agent 127.0.0.1 --ports 2121,2222,8080,44500,33060,18180
```

The agent runs 5 phases automatically:
1. **Passive Recon** — WHOIS, DNS, OSINT
2. **Active Scan** — nmap, nikto, gobuster, enum4linux
3. **Intelligence** — CVE RAG + fine-tuned model analysis
4. **Exploitation** — Metasploit module staging
5. **Report** — Markdown + HTML dashboard

### 3. View your report
```bash
open reports/report_127_0_0_1_*.html
```

**Expected findings on Metasploitable2:**
- CVE-2011-2523 — vsftpd 2.3.4 backdoor (CVSS 9.8)
- CVE-2007-2447 — Samba 3.0.20 RCE (CVSS 10.0)
- 3 CRITICAL · 5 HIGH · 1 MEDIUM findings
- Root shells confirmed via vsftpd backdoor + Samba usermap exploit

---

## Security Rules

- **Never commit `.env`** — API keys must stay local
- **Agent suggests exploits, never executes them autonomously**
- **Only scan systems you own or have written permission to test**
