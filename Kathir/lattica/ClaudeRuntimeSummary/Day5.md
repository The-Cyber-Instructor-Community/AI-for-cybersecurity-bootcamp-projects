# Day 5 Runtime Summary — Agentic Remediation Layer

**Date:** 2026-07-05
**Goal:** Build the AI-powered remediation layer with two delivery paths: a provider-agnostic LLM integration for the web dashboard (API key users) and a Claude Code agent + skills for terminal users (Pro subscription users). Same backend, two interfaces.

---

## What Was Built

### 1. Provider-Agnostic LLM Remediation Service (Backend)

Created `app/services/remediation.py` — the core AI remediation engine. Designed with a clean abstraction layer so the LLM provider can be swapped without touching the domain logic.

**Architecture:**

```
LLMProvider (abstract base class)
    ├── GeminiProvider     — Google Gemini API (free tier available)
    ├── OpenAIProvider     — OpenAI GPT models
    ├── ClaudeProvider     — Anthropic Claude API
    └── OllamaProvider     — Local Ollama (no API key needed)
```

**Key components:**
- `LLMProvider` — abstract base with one method: `generate(system_prompt, user_prompt) → (text, model)`
- Four provider adapters — each imports its SDK lazily (only when used), so unused providers don't add startup cost
- `SYSTEM_PROMPT` — a shared PQC expert personality prompt used by all providers. Instructs the LLM to return structured sections: Summary, Risk Explanation, Migration Steps, Priority
- `_build_user_prompt()` — constructs the finding-specific context (severity, HNDL score, S/R values, Tier 1 guidance) for the LLM
- `_parse_response()` — extracts the four sections from the LLM's raw text, with graceful fallback if formatting is imperfect
- `get_provider()` — factory function that creates the right provider from a name string + API key
- `get_remediation()` — single entry point: takes a finding context + provider config, returns structured remediation

**Why provider-agnostic:** The user has a Claude Pro subscription but no API credits. Building for any provider means the user can test with Gemini's free tier, evaluators can use whatever key they have, and the architecture demonstrates real-world LLM integration patterns — more impressive than hardcoding one provider.

### 2. Remediation API Endpoint (Backend)

Created `app/routers/remediation.py` — a single endpoint:

```
POST /scans/{scan_id}/findings/{finding_id}/remediate
```

**Request body:**
```json
{
  "provider": "gemini",
  "api_key": "user-provided-key",
  "model": ""
}
```

**API key resolution chain:**
1. User-provided key in request body (highest priority)
2. `REMEDIATION_API_KEY` from `.env`
3. `ANTHROPIC_API_KEY` from `.env` (legacy fallback)
4. Error if none found (except Ollama, which needs no key)

**Flow:** Load scan + finding from DB → build RemediationRequest with all context → call configured LLM provider → parse response → return structured RemediationResponse.

### 3. Updated Backend Configuration

- `app/core/config.py` — added `REMEDIATION_PROVIDER`, `REMEDIATION_API_KEY`, `REMEDIATION_MODEL` settings
- `.env` — added provider config section with comments
- `requirements.txt` — added `google-genai>=1.0.0` (Gemini SDK) and `httpx>=0.27.0` (Ollama HTTP calls)
- `app/main.py` — registered the remediation router on the `/scans` prefix

### 4. Pydantic Schemas for Remediation

Added to `app/models/schemas.py`:
- `RemediationRequest` — provider, api_key, model fields
- `RemediationResponse` — summary, risk_explanation, migration_steps, priority, provider, model

### 5. Dashboard: AI Deep Dive Button (Frontend)

Updated `FindingsTable.tsx` to add the AI deep dive within each expanded finding row:

- **"AI Deep Dive" button** — appears below the Tier 1 guidance (NIST deadline, PQC replacement, migration notes)
- **Loading state** — small spinner with "Generating remediation plan..." while the LLM responds
- **Error state** — red banner with error message and "Retry" button
- **Remediation response display** — structured card with:
  - Header showing "AI Remediation Plan" + provider/model attribution
  - Four sections: Summary, Risk Explanation, Migration Steps, Priority
  - Accent-colored section headers, pre-wrapped text for preserving step formatting
- Button disappears after a successful response (replaced by the response card)
- Each finding's remediation state is independent (loading, error, response tracked per finding ID)

### 6. LLM Settings Panel (Frontend)

Created `LLMSettings.tsx` — a collapsible sidebar panel for configuring the AI provider:

- **Provider selector** — dropdown with Gemini, OpenAI, Claude, Ollama + descriptions
- **API key input** — password field, only shown for providers that need a key. Hint text: "Free at aistudio.google.com" for Gemini
- **Model override** — optional text input for non-default models
- **Collapsible** — starts closed to keep sidebar clean, shows current provider name when collapsed

State lives in `App.tsx` and flows down through `FindingsTable` to the remediation API call.

### 7. Lattica PQC Advisor Agent (Claude Code)

Created `~/.claude/agents/lattica-pqc-advisor.md` — a Claude Code agent for terminal users who have a Pro subscription but no API key.

**Persona:** Dr. Rho Vasquez — "The Quantum Migration Strategist." Former NIST Cryptographic Technology Group, now consulting. Reads cipher suites like a radiologist reads X-rays.

**Frontmatter:**
```yaml
name: lattica-pqc-advisor
model: sonnet
color: indigo
tools: Read, Bash, Write, Grep, Glob
maxTurns: 25
```

**Startup:** Resolves `$HOME` first (to avoid `/root/` path errors), then loads the Context file. Non-negotiable — won't proceed without it.

**Design pattern:** Same as the Recon by Committee agents — lightweight agent definition with persona + startup hook, heavy Context file with the full SOP. Agent definition is the "who," Context file is the "how."

### 8. LatticaContext.md (Agent Context File)

Created `~/.claude/skills/Agents/LatticaContext.md` — the full operating procedure for the agent. Contains:

- **Mission statement** — scan, score, advise
- **API reference** — all four endpoints with curl examples and response shapes
- **HNDL scoring model** — complete S, R, E scales with descriptions, severity bucket thresholds
- **NIST standards reference** — SP 800-131A, IR 8547, CNSA 2.0, FIPS 203/204/205
- **PQC algorithm recommendations** — ML-KEM-768 for key exchange, ML-DSA-65 for signing, SLH-DSA for conservative use
- **Library support table** — OpenSSL 3.5+, BoringSSL, liboqs, AWS-LC, GnuTLS
- **6-step procedure** — preflight → gather parameters → scan → present → deep dive → assessment
- **Tier 1 vs Tier 2 output template** — explicit format showing "TIER 1 — Backend Assessment (deterministic)" separate from "TIER 2 — AI Deep Dive"
- **Edge cases** — backend not running, scan fails, zero findings, all-low findings, private domains, scan comparison

### 9. Slash Command Skills (Project-Level)

Created three project-level skills in `.claude/commands/`:

| Skill | File | Purpose |
|-------|------|---------|
| `/scan` | `scan.md` | Scan a domain: `/scan cloudflare.com S=4 R=3` |
| `/remediate` | `remediate.md` | Deep dive on latest or specified scan: `/remediate 5` |
| `/report` | `report.md` | Generate full PQC readiness report saved to `reports/` |

Each skill includes argument parsing instructions, expected output format, and error handling guidance.

---

## Problems Encountered and Fixes Applied

### Problem 1: User Has No API Key or Budget

**What happened:** User has Claude Pro subscription but no API credits for any provider. Can't test the dashboard's AI Deep Dive feature.

**Outcome:** Designed two delivery paths:
- Dashboard: API key users get inline remediation (Gemini free tier recommended)
- Terminal: Pro subscription users get the same analysis via the Claude Code agent (no API key needed — Claude Code IS the AI layer)

This turned a limitation into a stronger architecture — provider-agnostic backend + agent-based alternative.

### Problem 2: Agent Used Wrong Path for Context File (Test 1)

**What happened:** First test of the agent tried `/root/.claude/skills/Agents/LatticaContext.md` instead of `/home/jamiraquai/.claude/...`. The `~` in the startup instructions resolved to `/root/` in the agent's context.

**Fix applied:** Updated the agent definition to:
1. Run `echo $HOME` via Bash as the first action to get the actual home directory
2. Use the resolved path to read the Context file
3. Explicit note: "The home directory on this system is `/home/jamiraquai`, NOT `/root/`"

**Verified:** Test 2 loaded the Context on the first try with zero errors.

### Problem 3: Agent Blended Tier 1 and Tier 2 Analysis (Test 1)

**What happened:** Deep dives mixed the backend's deterministic guidance (nist_deadline, pqc_replacement, migration_notes from crypto_mappings.py) with the agent's own AI analysis, making it unclear which was which.

**Fix applied:** Added explicit Tier 1 / Tier 2 output template to LatticaContext.md:
- "TIER 1 — Backend Assessment (deterministic):" with verbatim API fields
- "TIER 2 — AI Deep Dive:" with the agent's expert analysis

**Verified:** Test 2 clearly separated both tiers in every deep dive. Agent followed the instruction to present Tier 1 data as-is without rephrasing.

---

## Test Results

### Test 1: google.com (S=5, R=5)

- **Findings:** 22 total — 10 critical, 12 high, 0 medium, 0 low
- **Peak risk:** 125/125 (max possible with S=5 × R=5 × E=5)
- **Issues found:** Wrong Context path, no Tier 1/Tier 2 separation
- **Output quality:** Technically accurate, well-grouped, good remediation advice
- **Session time:** ~3 minutes 16 seconds

### Test 2: cloudflare.com (S=4, R=3)

- **Findings:** 35 total — 0 critical, 17 high, 4 medium, 14 low (distribution shifted due to lower S/R)
- **Peak risk:** 60/125 (capped by S=4 × R=3 × E=5 = 60)
- **Issues found:** None significant — both fixes confirmed working
- **Output quality:** Excellent — smart grouping of 35 findings, correct math ceiling insight, concrete config snippets, clear Tier 1/Tier 2 separation
- **Session time:** 4 tool calls, no retries

### Dashboard API Endpoint

- Backend started cleanly with the new remediation router
- All 5 endpoints confirmed via OpenAPI: `GET/POST /scans/`, `GET /scans/{id}`, `POST /scans/{id}/findings/{id}/remediate`, `GET /health`
- Frontend compiled cleanly: 81 modules, no errors
- Not tested end-to-end with a real API key (user has no credits)

---

## Design Decisions Made

### Provider-Agnostic over Single-Provider

Built an abstract `LLMProvider` base class with four adapters instead of hardcoding Claude or Gemini. The prompt engineering and response parsing are shared — only the API call mechanics differ per provider. This means:
- Users pick whichever provider they have access to
- Evaluators can plug in any key
- The architecture demonstrates enterprise patterns (provider abstraction, dependency injection)

### Agent + Skills over CLI Tool

Instead of building a separate command-line application, built a Claude Code agent with project-level slash commands. This means:
- No new code to maintain — the agent calls the existing backend API
- Claude Code IS the AI layer — no API key needed for Pro subscribers
- The agent inherits Claude's conversational abilities (follow-ups, clarifications, comparisons)
- Skills (`/scan`, `/remediate`, `/report`) give repeatability without ambiguity

### Agent-Context Separation Pattern

Following the Recon by Committee architecture: lightweight agent definition (persona + startup hook) with a heavy Context file (full SOP). This means:
- Can update the procedure without touching the agent persona
- Can update the persona without touching the procedure
- Context file is reusable across different agent definitions if needed

### Tier 1 / Tier 2 Separation

Deterministic guidance from `crypto_mappings.py` (Tier 1) is presented separately from the AI's expert analysis (Tier 2). This ensures:
- Users can see exactly what the backend produced vs. what the AI added
- The deterministic layer is trustworthy even if the AI hallucinates
- Evaluators can verify both layers independently

### Shared Database Between Dashboard and Agent

Both the React dashboard and the Claude Code agent hit the same `POST /scans/` endpoint and the same SQLite database. A scan created by the agent appears in the dashboard's scan history, and vice versa. This was confirmed during testing — the user noticed agent scans showing up in the dashboard.

---

## Files Created/Modified

| File | Action | Description |
|------|--------|-------------|
| `backend/app/services/remediation.py` | Created | Provider-agnostic LLM service (4 adapters, shared prompt, response parser) |
| `backend/app/routers/remediation.py` | Created | POST /remediate endpoint with API key resolution chain |
| `backend/app/models/schemas.py` | Modified | Added RemediationRequest/RemediationResponse schemas |
| `backend/app/core/config.py` | Modified | Added REMEDIATION_PROVIDER/API_KEY/MODEL settings |
| `backend/app/main.py` | Modified | Registered remediation router |
| `backend/.env` | Modified | Added provider config section |
| `backend/requirements.txt` | Modified | Added google-genai, httpx |
| `frontend/src/components/LLMSettings.tsx` | Created | Provider selection + API key input panel |
| `frontend/src/components/LLMSettings.css` | Created | Settings panel styling |
| `frontend/src/components/FindingsTable.tsx` | Modified | Added deep dive button, loading/error states, response display |
| `frontend/src/components/FindingsTable.css` | Modified | Added deep dive section styles |
| `frontend/src/App.tsx` | Modified | Added LLM config state, LLMSettings component, passed config to FindingsTable |
| `frontend/src/types/index.ts` | Modified | Added RemediationRequest/RemediationResponse interfaces |
| `frontend/src/services/api.ts` | Modified | Added requestRemediation function |
| `~/.claude/agents/lattica-pqc-advisor.md` | Created | PQC advisor agent definition (Dr. Rho Vasquez persona) |
| `~/.claude/skills/Agents/LatticaContext.md` | Created | Full SOP: API reference, HNDL model, NIST standards, procedure, output format |
| `.claude/commands/scan.md` | Created | /scan skill — scan a domain from the terminal |
| `.claude/commands/remediate.md` | Created | /remediate skill — deep dive analysis |
| `.claude/commands/report.md` | Created | /report skill — generate full PQC readiness report |

---

## Architecture at End of Day 5

```
Dashboard users (API key)         Terminal users (Pro subscription)
┌──────────────────────┐          ┌──────────────────────────────┐
│  React Dashboard     │          │  claude --agent              │
│  (localhost:5173)    │          │    lattica-pqc-advisor       │
│                      │          │                              │
│  ScanForm            │          │  /scan cloudflare.com S=4 R=3│
│  LLMSettings         │          │  /remediate                  │
│  FindingsTable       │          │  /report                     │
│    └─ AI Deep Dive   │          │                              │
│       (Gemini/OpenAI/│          │  Claude IS the AI layer      │
│        Claude/Ollama)│          │  (no API key needed)         │
└──────┬───────────────┘          └──────────┬───────────────────┘
       │ (axios)                             │ (curl)
       ▼                                     ▼
┌──────────────────────────────────────────────────┐
│              FastAPI Backend (:8000)              │
│                                                  │
│  POST /scans/              → sslyze scan         │
│  GET  /scans/              → list scans          │
│  GET  /scans/{id}          → full results        │
│  POST /scans/{id}/findings/{id}/remediate        │
│       → LLM provider → structured remediation    │
│                                                  │
│  sslyze → crypto_mappings → HNDL scorer → SQLite │
└──────────────────────────────────────────────────┘
```

---

## What's Next (Day 6)

Polish and UX improvements:
1. **Interactive S/R prompting** — Agent asks for domain first, then walks users through S and R scales with descriptions instead of requiring `S=4 R=3` upfront
2. Edge case handling and error states
3. UI polish on the dashboard
4. Any remaining bugs from testing
