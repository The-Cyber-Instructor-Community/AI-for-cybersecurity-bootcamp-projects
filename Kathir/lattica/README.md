# Lattica — Post-Quantum Cryptography Readiness Tool

Lattica scans TLS endpoints for quantum-vulnerable cryptography and scores every finding using the **HNDL (Harvest Now, Decrypt Later) risk model**. It doesn't just inventory what you're running — it tells you *how urgently you need to migrate* based on your data's sensitivity and retention requirements.

Two ways to use it:

| Path | For | Interface | AI Remediation Via |
|------|-----|-----------|-------------------|
| **Dashboard** | API key users | React web app | Any LLM provider (Gemini, OpenAI, Claude, Ollama) |
| **AI Harness** | Subscription users | Claude Code / Codex / Hermes | The harness itself — no API key needed |

Both paths hit the same backend, same scan engine, same scoring. The only difference is how the AI remediation layer is delivered.

---

## Quick Start

```bash
git clone https://github.com/kathirselvanwork-cmd/lattica.git
cd lattica

# Backend only (required for both paths)
./setup.sh

# Backend + dashboard
./setup.sh --dashboard

# Backend + Claude Code agent
./setup.sh --agent

# Everything
./setup.sh --all
```

Then configure your environment:

```bash
# Edit backend/.env — add your LLM API key if you want AI Deep Dive (optional)
nano backend/.env
```

The backend works with zero configuration — scanning, HNDL scoring, and Tier 1 guidance all run without any API keys. The `.env` is only needed if you want Tier 2 AI remediation via the dashboard. The agent path needs no API keys at all.

Then start the backend:

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Architecture

```
Dashboard (API key users)             AI Harness (subscription users)
┌──────────────────────────┐          ┌────────────────────────────────┐
│  React Dashboard         │          │  Claude Code / Codex / Hermes  │
│  (localhost:5173)        │          │                                │
│                          │          │  /scan example.com             │
│  ScanForm                │          │  /remediate                    │
│  LLMSettings             │          │  /report                       │
│  FindingsTable           │          │                                │
│    └─ AI Deep Dive       │          │  The harness IS the AI layer   │
│       (Gemini/OpenAI/    │          │  (no API key needed)           │
│        Claude/Ollama)    │          │                                │
└──────────┬───────────────┘          └──────────┬─────────────────────┘
           │ axios                               │ curl
           ▼                                     ▼
┌──────────────────────────────────────────────────────┐
│                FastAPI Backend (:8000)                │
│                                                      │
│  POST /scans/                  → sslyze TLS scan     │
│  GET  /scans/                  → list past scans     │
│  GET  /scans/{id}              → full scan results   │
│  POST /scans/{id}/findings/{id}/remediate            │
│       → LLM provider → structured remediation        │
│                                                      │
│  sslyze → crypto_mappings → HNDL scorer → SQLite     │
└──────────────────────────────────────────────────────┘
```

---

## Option A: Dashboard (API Key Users)

The dashboard is a React app that talks to the backend. Best for users who have an API key for any LLM provider.

### Setup

```bash
./setup.sh --dashboard
```

### Running

Start both the backend and frontend:

```bash
# Terminal 1 — backend
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — frontend
cd frontend
bun run dev
```

Open **http://localhost:5173**.

### Usage

1. **Enter a domain** (e.g., `api.example.com`) in the scan form
2. **Set Data Sensitivity (S)** and **Retention Horizon (R)** using the sliders — these shape the HNDL risk scores
3. **Click Scan** — the backend runs sslyze against the target (5–15 seconds)
4. **Review findings** — sorted by HNDL risk, color-coded by severity
5. **AI Deep Dive** (optional) — expand any finding and click "AI Deep Dive" for a detailed remediation plan

### LLM Provider Setup

Configure the AI Deep Dive provider in the sidebar **LLM Settings** panel:

| Provider | API Key | Notes |
|----------|---------|-------|
| **Gemini** | Free at [aistudio.google.com](https://aistudio.google.com/apikey) | Recommended — free tier works |
| **OpenAI** | [platform.openai.com](https://platform.openai.com/api-keys) | GPT-4o or later |
| **Claude** | [console.anthropic.com](https://console.anthropic.com/) | Requires API credits |
| **Ollama** | None needed | Runs locally — install from [ollama.com](https://ollama.com) |

The AI Deep Dive is optional. Without it, you still get the full scan, HNDL scores, and Tier 1 deterministic guidance (NIST deadlines, PQC replacements, migration notes).

---

## Option B: AI Harness (Subscription Users)

For users who have a subscription to an AI coding tool (Claude Code, OpenAI Codex, Hermes, etc.) but no API key. The harness itself acts as the AI remediation layer — it calls the Lattica backend for scan data and provides expert analysis using its own reasoning.

### Claude Code Setup

```bash
./setup.sh --agent
```

This copies the agent definition and context file to `~/.claude/`. The slash commands (`/scan`, `/remediate`, `/report`) are project-level and work automatically.

### Running

Start the backend, then launch the agent:

```bash
# Terminal 1 — backend (required)
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — agent
cd lattica
claude --agent lattica-pqc-advisor
```

### Usage

Talk to the agent naturally or use slash commands:

```
You: Scan cloudflare.com
Agent: What type of data flows over this connection? [presents S scale]
You: 4
Agent: How long must this data stay confidential? [presents R scale]
You: 3
Agent: [runs scan, presents findings with Tier 1 + Tier 2 analysis]
```

**Slash commands:**

| Command | Purpose | Example |
|---------|---------|---------|
| `/scan` | Scan a domain | `/scan example.com` or `/scan example.com S=4 R=3` |
| `/remediate` | Deep dive on the latest scan | `/remediate` |
| `/report` | Generate a full PQC readiness report | `/report` (saves to `reports/`) |

### Other Harnesses (Codex, Hermes, etc.)

The `agent/` directory contains two files that define the agent's behavior:

- **`lattica-pqc-advisor.md`** — persona, startup procedure, output format, rules of engagement
- **`LatticaContext.md`** — full operating procedure: API reference, HNDL model, NIST standards, PQC algorithms, step-by-step procedure

To adapt for a different harness:
1. Use `lattica-pqc-advisor.md` as the system prompt or agent definition
2. Use `LatticaContext.md` as the context/knowledge file
3. The backend API is the same — `POST http://localhost:8000/scans/` etc.
4. The slash commands in `.claude/commands/` can be adapted to your harness's skill/command format

---

## The HNDL Risk Model

**Harvest Now, Decrypt Later (HNDL)** is a threat where adversaries record encrypted traffic today and wait for quantum computers to break the encryption later. If the data is still sensitive when that happens, confidentiality is retroactively lost.

### Scoring Formula

```
S × R × E = HNDL Risk Score (1–125)
```

| Factor | Name | Range | What It Measures | Source |
|--------|------|-------|------------------|--------|
| **S** | Data Sensitivity | 1–5 | How sensitive is the data? | You decide |
| **R** | Retention Horizon | 1–5 | How long must it stay confidential? | You decide |
| **E** | Crypto Exposure | 1–5 | How vulnerable is this crypto to quantum attack? | Auto-detected |

**S and R are what make Lattica a risk modeler, not just a scanner.** The same cipher suite gets a very different risk score depending on whether it's protecting public blog posts (S=1) or health records (S=5), and whether the data expires in days (R=1) or must be retained for a decade (R=5).

### Severity Buckets

| Severity | Score Range | Meaning | Action |
|----------|-------------|---------|--------|
| **Critical** | 76–125 | Sensitive long-retention data behind quantum-vulnerable crypto | Migrate immediately |
| **High** | 36–75 | Significant exposure on two or more axes | Plan migration within 1–2 years |
| **Medium** | 11–35 | Some risk but lower priority | Monitor, include in PQC roadmap |
| **Low** | 1–10 | Minimal HNDL exposure | No urgent action |

### Remediation: Tier 1 vs Tier 2

Every finding comes with two layers of guidance:

- **Tier 1 (deterministic)** — NIST deadlines, PQC replacement algorithms, and migration notes. Generated from `crypto_mappings.py`. Always available, no AI needed.
- **Tier 2 (AI-powered)** — detailed remediation plans with specific libraries, config changes, and migration steps. Generated by the LLM provider (dashboard) or the AI harness (terminal).

---

## NIST Standards Reference

| Standard | Key Point |
|----------|-----------|
| **SP 800-131A Rev 2** | RSA/ECC deprecated 2030, disallowed 2035 |
| **IR 8547** | PQC transition timeline and migration guidance |
| **CNSA 2.0** | NSA PQC adoption timeline for national security systems |
| **FIPS 203 (ML-KEM)** | PQC key exchange — replaces RSA/ECDHE |
| **FIPS 204 (ML-DSA)** | PQC digital signatures — replaces RSA/ECDSA |
| **FIPS 205 (SLH-DSA)** | Alternative PQC signatures — stateless, hash-based |

---

## Project Structure

```
lattica/
├── backend/                  # FastAPI + sslyze + SQLite
│   ├── app/
│   │   ├── core/             # Config, database setup
│   │   ├── models/           # SQLAlchemy models, Pydantic schemas
│   │   ├── routers/          # API endpoints (scans, remediation)
│   │   ├── services/         # Scanner, HNDL scorer, crypto mappings, LLM remediation
│   │   └── main.py           # FastAPI app entry point
│   ├── requirements.txt
│   └── .env.example
├── frontend/                 # React + Vite + TypeScript
│   ├── src/
│   │   ├── components/       # ScanForm, FindingsTable, ScanHistory, SeverityChart, etc.
│   │   ├── services/         # API client (axios)
│   │   └── types/            # TypeScript interfaces
│   └── package.json
├── agent/                    # Claude Code agent (portable copies)
│   ├── lattica-pqc-advisor.md    # Agent definition + persona
│   └── LatticaContext.md         # Full operating procedure + knowledge base
├── .claude/commands/         # Project-level slash commands
│   ├── scan.md               # /scan
│   ├── remediate.md          # /remediate
│   └── report.md             # /report
├── ClaudeRuntimeSummary/     # Daily build logs (Days 1–7)
├── setup.sh                  # Installation script
└── README.md
```

---

## Prerequisites

| Tool | Version | Required For |
|------|---------|-------------|
| Python | 3.11+ | Backend |
| bun | any | Dashboard (frontend) |
| Claude Code | any | Agent path (optional) |

---

## Disclaimer

**Only scan domains you own or have explicit permission to test.** Lattica uses [sslyze](https://github.com/nabla-c0/sslyze) to perform TLS scans, which involves connecting to the target server and probing its TLS configuration. While this is non-intrusive (it only reads publicly available TLS handshake data), scanning systems without authorization may violate local laws or the target's terms of service.

This tool is intended for:
- Assessing your own infrastructure's PQC readiness
- Authorized security assessments and penetration testing
- Educational and research purposes

The authors are not responsible for misuse of this tool.

---

## License

This project was built as a bootcamp capstone. See individual dependencies for their respective licenses.
