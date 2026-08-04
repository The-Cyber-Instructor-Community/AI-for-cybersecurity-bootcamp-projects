# AutoRedTeam — Threat Model

**Version:** 1.0  
**Date:** 2026-07-15  
**Frameworks:** STRIDE (infrastructure) + MITRE ATLAS (AI/ML layer)  
**Status:** Mitigations applied — see [ATLAS_ASSESSMENT.md](ATLAS_ASSESSMENT.md)

---

## 1. System Overview

AutoRedTeam is an AI-powered autonomous penetration testing agent. It has four major components that cross trust boundaries and therefore define the attack surface:

```
┌─────────────────────────────────────────────────────────────────────┐
│  TRUST ZONE A — macOS Host (fully trusted)                         │
│                                                                     │
│  ┌──────────────────┐    ┌───────────────┐    ┌─────────────────┐  │
│  │  agent/agent.py  │───▶│  ChromaDB RAG │    │  Llama 3.1 8B   │  │
│  │  (orchestrator)  │    │  (local disk) │    │  (local model)  │  │
│  └────────┬─────────┘    └───────────────┘    └─────────────────┘  │
│           │                                                         │
└───────────┼─────────────────────────────────────────────────────────┘
            │  ① HTTP/REST (no TLS) — TRUST BOUNDARY CROSSING
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  TRUST ZONE B — UTM Shared Network 192.168.64.0/24                 │
│                                                                     │
│  ┌──────────────────────────┐        ┌──────────────────────────┐  │
│  │  Kali Linux (64.7)       │──②──▶ │  Metasploitable2 (64.8)  │  │
│  │  kali_mcp_server/        │  msf   │  (target — untrusted)    │  │
│  │  server.py :8765         │        │                          │  │
│  └──────────────────────────┘        └──────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
            │  ③ HTTPS — external API call
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  TRUST ZONE C — Internet (untrusted)                               │
│  Anthropic API · NVD API · MITRE ATT&CK STIX bundle               │
└─────────────────────────────────────────────────────────────────────┘
```

### Trust Boundary Summary

| Boundary | Path | Protocol | Risk Level |
|----------|------|----------|-----------|
| ① Agent → Kali MCP | macOS → 192.168.64.7:8765 | HTTP (plaintext) | HIGH |
| ② Kali → Target | 192.168.64.7 → 192.168.64.8 | TCP/various | HIGH (target untrusted) |
| ③ Agent → Internet | macOS → api.anthropic.com / nvd.nist.gov | HTTPS | MEDIUM |
| ④ Target → MCP | 192.168.64.8 → 192.168.64.7:8765 | HTTP | CRITICAL (pivot risk) |

Boundary ④ is the most dangerous: after Kali exploits Metasploitable2, the target has a shell on the network and can reach back to the MCP server. This is a **post-exploitation pivot** back to the attacker's own infrastructure.

---

## 2. Assets Being Protected

| Asset | Location | Confidentiality | Integrity | Availability |
|-------|----------|----------------|-----------|--------------|
| Anthropic API key | `.env` | CRITICAL | HIGH | MEDIUM |
| NVD API key | `.env` | MEDIUM | LOW | LOW |
| MCP API token | `.env` | HIGH | HIGH | MEDIUM |
| Fine-tuned model weights | `models/autoredteam_lora/` | MEDIUM | HIGH | MEDIUM |
| ChromaDB CVE vectors | `chroma_db/` | LOW | HIGH | MEDIUM |
| Fine-tuning dataset | `data/finetune_dataset.jsonl` | LOW | HIGH | LOW |
| Pentest reports | `reports/` | HIGH | HIGH | LOW |
| SYSTEM_PROMPT | `agent/agent.py` | MEDIUM | HIGH | HIGH |
| Kali VM integrity | `192.168.64.7` | HIGH | CRITICAL | HIGH |

---

## 3. Threat Actors

| Actor | Motivation | Capability | Entry Point |
|-------|-----------|-----------|------------|
| **Adversarial target** | Detect/evade scan, pivot to attacker infra | LOW–HIGH (depends on target) | Crafted service banners, HTTP responses |
| **Network observer** | Intercept tool args, harvest API keys | LOW (same subnet required) | Passive sniff on 192.168.64.x |
| **Open-source attacker** | Poison training data in community repo | LOW | GitHub PR to modify `finetune_dataset.jsonl` |
| **Compromised supply chain** | Poisoned CVE data, malicious dependencies | LOW (NVD is trusted; pip is risk) | NVD API MITM, malicious package update |

---

## 4. STRIDE Analysis by Component

### 4A — Agent Orchestrator (`agent/agent.py`)

| STRIDE | Threat | Specific Risk | Mitigation | Status |
|--------|--------|--------------|------------|--------|
| **Spoofing** | Target impersonates a safe system | Service returns benign banner but is hostile | None — agent trusts all tool output | ⚠️ Partial (sanitizer catches injection phrases) |
| **Tampering** | Tool output modified in transit | HTTP response from Kali MCP altered by MITM on LAN | No TLS on boundary ① | ⚠️ Open (TLS not yet implemented) |
| **Repudiation** | No audit trail of tool calls | Agent could misreport what tools it ran | None — no immutable log | ⚠️ Open |
| **Info Disclosure** | API key exposed via prompt injection | Injection causes agent to echo `ANTHROPIC_API_KEY` from env | Sanitize tool outputs | ✅ Fixed |
| **Denial of Service** | Runaway tool calls exhaust API budget | Agent loops on a rich target | `MAX_TOOL_CALLS = 40` guard | ✅ Mitigated |
| **Elevation of Privilege** | Prompt injection overrides SYSTEM_PROMPT | Target causes agent to skip exploitation safety rules | Output sanitizer flags injection patterns | ✅ Fixed |

---

### 4B — Kali MCP Server (`kali_mcp_server/server.py`)

This is the highest-risk component because it is a **remote code execution endpoint** on the network.

| STRIDE | Threat | Specific Risk | Mitigation | Status |
|--------|--------|--------------|------------|--------|
| **Spoofing** | Any host impersonates the macOS agent | No client auth — any IP can POST `/call` | Bearer token auth on `/call` | ✅ Fixed |
| **Tampering** | Request body modified in transit | Tool args altered between agent and Kali | No TLS on boundary ① | ⚠️ Open |
| **Repudiation** | Attacker runs tools, no log | Malicious calls leave no evidence | No request logging implemented | ⚠️ Open |
| **Info Disclosure** | Kali environment exposed | `shell` tool can `cat /etc/shadow`, `env` | Bearer token blocks unauthenticated access | ✅ Fixed |
| **Denial of Service** | Flood `/call` with long-running tools | `timeout` parameter limits per-call time | Per-call timeout implemented | ✅ Mitigated |
| **Elevation of Privilege** | `shell` tool bypasses allowlist | `/bin/bash -c <any command>` is unrestricted | Auth required; consider removing `shell` from ALLOWED | ⚠️ Partial |

#### Unique Risk — Post-Exploitation Pivot (Boundary ④)

After Kali successfully exploits Metasploitable2, the target gains a shell on `192.168.64.x`. From that shell:

```bash
# Attacker on Metasploitable2 can discover and call the MCP server:
curl -X POST http://192.168.64.7:8765/call \
  -H "Content-Type: application/json" \
  -d '{"category":"post_exploit","tool":"shell","args":["id"]}'
```

**Before fix:** Any request succeeds — Metasploitable2 owns Kali.  
**After fix:** Requires `Authorization: Bearer <token>` — token is never sent to target.

---

### 4C — RAG Layer (ChromaDB + NVD ingestion)

| STRIDE | Threat | Specific Risk | Mitigation | Status |
|--------|--------|--------------|------------|--------|
| **Tampering** | Poisoned CVE data from NVD | MITM on NVD API injects false CVE severity | HTTPS with CA verification (requests default) | ✅ Mitigated |
| **Tampering** | Poisoned fine-tuning dataset | PR to community repo modifies `finetune_dataset.jsonl` | None — file is publicly writable in repo | ⚠️ Open |
| **Info Disclosure** | ChromaDB contents exposed | `chroma_db/` directory readable by any local process | Local filesystem permissions (macOS) | ✅ Acceptable |
| **Tampering** | Malicious pip package | `sentence-transformers` or `chromadb` update with backdoor | Pin dependency versions in `requirements.txt` | ⚠️ Open |

---

### 4D — Fine-Tuned Model (`models/autoredteam_lora/`)

| STRIDE | Threat | Specific Risk | Mitigation | Status |
|--------|--------|--------------|------------|--------|
| **Tampering** | Model weights modified on disk | Attacker with filesystem access changes Llama weights | Gitignored — not in repo; local disk only | ✅ Acceptable |
| **Info Disclosure** | Model memorized training secrets | If training data contained secrets, model could regurgitate | Training data is NVD public CVEs only | ✅ Acceptable |
| **Tampering** | Adversarial input to fine-tuned model | Crafted CVE text causes model to output exploit code | Claude fallback doesn't use local model if unavailable | ✅ Mitigated |

---

### 4E — External API Calls (Boundary ③)

| STRIDE | Threat | Specific Risk | Mitigation | Status |
|--------|--------|--------------|------------|--------|
| **Spoofing** | Anthropic API impersonation | MITM serves false Claude responses | HTTPS with CA verification | ✅ Mitigated |
| **Info Disclosure** | API key leaks to git | `ANTHROPIC_API_KEY` committed | `.env` in `.gitignore` | ✅ Mitigated |
| **Denial of Service** | API rate limit exhaustion | Excessive calls exhaust quota | `MAX_TOOL_CALLS = 40`; monthly spend cap recommended | ✅ Partial |
| **Info Disclosure** | Target data sent to Anthropic | Pentest findings (IPs, usernames) sent in API calls | Anthropic's data processing agreement applies | ⚠️ Accepted risk |

---

## 5. AI-Specific Threats (MITRE ATLAS)

| ATLAS Technique | Description | Component | Status |
|----------------|-------------|-----------|--------|
| **AML.T0051** — Prompt Injection | Target embeds LLM instructions in service banners | Agent orchestrator | ✅ Sanitizer added |
| **AML.T0056** — Plugin Compromise | Unauthenticated MCP server exploited | Kali MCP server | ✅ Bearer token added |
| **AML.T0048** — Meta Prompt Extraction | SYSTEM_PROMPT extracted via injection | Agent orchestrator | ⚠️ Partially mitigated |
| **AML.T0034** — Cost Harvesting | API key exfiltrated, used at owner's expense | Agent + .env | ✅ Key gitignored; spend cap recommended |
| **AML.T0020** — Training Data Poisoning | Public dataset modified via PR | fine-tuning pipeline | ⚠️ No checksum verification |
| **AML.T0040** — Model Inference API Access | API key grants unlimited Claude access | config.py | ✅ Gitignored; accepted risk |

Full details and remediation code in [ATLAS_ASSESSMENT.md](ATLAS_ASSESSMENT.md).

---

## 6. Security Controls in Place

| Control | Where | Covers |
|---------|-------|--------|
| Tool allowlist | `server.py` ALLOWED dict | Prevents arbitrary binary execution |
| Bearer token auth | `server.py` + `kali_client.py` | Blocks unauthenticated MCP access |
| Output sanitizer | `agent.py` `sanitize_tool_output()` | Detects prompt injection in tool results |
| MAX_TOOL_CALLS = 40 | `agent.py` | Prevents runaway API spend |
| .env gitignored | `.gitignore` | API keys never committed |
| reports/ gitignored | `.gitignore` | Target data never committed |
| HTTPS for all external APIs | `requests`, `httpx` defaults | Prevents MITM on external calls |
| "suggest only" in SYSTEM_PROMPT | `agent.py` | Prevents autonomous destructive execution |
| Graceful Kali fallback | `kali_client.py` | Agent continues if MCP server offline |

---

## 7. Open Risks (Accepted or Unmitigated)

| Risk | Reason Not Fixed | Recommended Next Step |
|------|-----------------|----------------------|
| Plain HTTP on boundary ① | Lab-only; TLS adds cert management overhead | Add self-signed cert + `verify=False` in kali_client for real engagements |
| `shell` in post_exploit allowlist | Needed for legitimate post-exploit tasks | Remove from allowlist; replace with explicit command list |
| No request logging on MCP server | Not implemented in v1 | Add structured log: `{"ts","src_ip","category","tool","args","result_code"}` |
| No fine-tuning dataset checksum | Dataset is public in repo | Add `sha256sum` check before `finetune/train.py` runs |
| Target data sent to Anthropic API | Inherent in cloud LLM use | Use local Ollama model for sensitive engagements |

---

## 8. Residual Risk Rating

| Component | Inherent Risk | Controls Applied | Residual Risk |
|-----------|-------------|-----------------|---------------|
| Kali MCP Server | CRITICAL | Auth token, allowlist | MEDIUM |
| Agent agentic loop | HIGH | Output sanitizer, tool limits | MEDIUM |
| RAG / fine-tuning pipeline | MEDIUM | HTTPS on NVD; local ChromaDB | LOW |
| External API calls | MEDIUM | HTTPS, gitignored keys | LOW |
| Pentest reports | HIGH | gitignored reports/ | LOW |

**Overall residual risk: MEDIUM** — acceptable for a lab environment; requires additional hardening (TLS, logging, dataset checksum) before use in production engagements.
