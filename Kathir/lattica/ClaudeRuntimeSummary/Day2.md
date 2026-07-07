# Day 2 Runtime Summary — HNDL Scoring Engine

**Date:** 2026-07-01
**Goal:** Build the HNDL scoring engine — crypto exposure mappings, composite risk calculation, severity bucketing, and deterministic Tier 1 remediation guidance. Wire it into the scan pipeline so findings come back fully scored.

---

## What Was Built

### 1. Crypto Exposure Mapping Table (`app/services/crypto_mappings.py`)

The knowledge base that powers HNDL scoring. Maps every crypto primitive Lattica might encounter in a TLS scan to four things:

- **Exposure score (1–5):** How soon a quantum computer breaks this primitive
- **NIST deadline:** When it's deprecated / disallowed per NIST IR 8547, CNSA 2.0
- **PQC replacement:** The specific NIST-standardized post-quantum algorithm to migrate to
- **Migration notes:** Tier 1 deterministic guidance — actionable, no AI needed

**Why this structure:** The mapping table is a `CryptoProfile` dataclass looked up via a single `get_crypto_profile(finding_type, value)` function. This gives us a clean separation — the scanner produces raw findings, the mapping table provides the crypto intelligence, and the scorer combines them with user context.

**Coverage:**

| Category | What's mapped | Score range | Key insight |
|----------|---------------|-------------|-------------|
| **Protocols** | SSL 2.0 through TLS 1.3 | 2–5 | SSL 2.0/3.0 and TLS 1.0/1.1 are already deprecated AND quantum-vulnerable (score 5). TLS 1.2 is transitional (score 3). TLS 1.3 is best available but ECDHE key exchange is still quantum-vulnerable (score 2). |
| **Cipher suites** | Classified by key exchange pattern, not enumerated individually | 2–5 | The key exchange is what quantum breaks (Shor's algorithm). Symmetric ciphers (AES, ChaCha20) and hashes (SHA-256/384) are quantum-resistant (Grover's only halves effective strength). Static RSA key exchange (score 4–5) is worse than ECDHE (score 3) because RSA lacks forward secrecy — breaking one key decrypts ALL past sessions. TLS 1.3 suites (score 2) mandate forward secrecy. |
| **Certificates** | RSA-1024 through RSA-4096, ECDSA-256/384/521, Ed25519, Ed448 | 3–5 | All quantum-vulnerable via Shor's. Key SIZE doesn't help against quantum — RSA-2048 and RSA-4096 fall with roughly equal effort (~4000 logical qubits). RSA-1024 scores 5 because it's classically weak too. |
| **Signature algorithms** | sha1/sha256/sha384/sha512 with RSA, ecdsa-with-SHA256/384 | 3–5 | The hash is quantum-safe; the signing KEY is the vulnerable component. SHA-1 variants score 5 (classically broken). |

**Design decisions:**
- Cipher suites are classified by **pattern matching** on the cipher name rather than enumerated individually. This is because there are hundreds of possible cipher suites, but they fall into a small number of key exchange families (static RSA, ECDHE, DHE, TLS 1.3). The `_classify_cipher_suite()` function checks prefixes and substrings to route to the right profile.
- Results are cached in `_cipher_cache` to avoid re-classifying the same suite across multiple scans.
- Fallback profiles exist for unrecognized primitives (score 3, "review manually") so the system never crashes on unexpected input.

**Sources cited in docstrings:**
- NIST SP 800-131A Rev 2
- NIST IR 8547 (PQC transition)
- CNSA 2.0 (NSA Commercial National Security Algorithm Suite)
- Google 2029 PQC timeline

### 2. HNDL Scoring Engine (`app/services/hndl_scorer.py`)

The core differentiator — the reasoning layer that transforms raw scan output into risk intelligence.

**The formula:** `HNDL Risk = S × R × E`

| Variable | Name | Range | Source |
|----------|------|-------|--------|
| S | Data Sensitivity | 1–5 | User-provided: "How sensitive is the data?" |
| R | Retention Horizon | 1–5 | User-provided: "How long must confidentiality hold?" |
| E | Crypto Exposure | 1–5 | Auto-derived from crypto_mappings.py |

**Composite score range:** 1–125

**Severity buckets:**

| Bucket | Score range | Meaning |
|--------|-------------|---------|
| Critical | 76–125 | Sensitive long-retention data behind weak crypto |
| High | 36–75 | Significant exposure on 2+ axes |
| Medium | 11–35 | Some risk, lower priority |
| Low | 1–10 | Minimal HNDL exposure |

**Why this model works (examples from docstring):**
- A public website (S=1) using RSA-2048 (E=4) scores LOW even with long retention — the data isn't secret, so HNDL doesn't apply.
- A healthcare API (S=5) using TLS 1.3 ECDHE (E=2) with 10-year retention (R=5) scores MEDIUM-HIGH — the crypto is decent but the data's value outlasts its protection timeline.
- A financial API (S=5) using static RSA key exchange (E=4) with regulatory retention (R=5) scores CRITICAL — exactly what HNDL attackers target.

**Output:** The scorer returns `ScoredFinding` dataclass objects sorted by HNDL risk score descending (worst findings first). Each includes the composite score, severity bucket, and all four fields from the crypto profile (exposure score, NIST deadline, PQC replacement, migration notes).

### 3. Scan Pipeline Integration (modified `app/routers/scans.py`)

Replaced the Day 1 stub (hardcoded `crypto_exposure_score=3`, `hndl_risk_score=0.0`, `severity_bucket="medium"`) with a call to `score_findings()`.

**The new scan flow:**
1. Client POSTs domain + HNDL context (S, R)
2. Create Scan record → RUNNING
3. Run sslyze → get raw findings
4. **NEW:** Pass raw findings + S + R through `score_findings()` → get scored findings
5. Store scored findings with all fields populated
6. Mark scan COMPLETED, return results

One import added (`from app.services.hndl_scorer import score_findings`), one block of code replaced. Clean integration.

---

## Problems Encountered and Fixes Applied

### Problem 1: Server Restart Race Condition (recurring from Day 1)

**What happened:** When restarting the server to pick up the new scoring code, `pkill -f "uvicorn"` followed by starting a new instance was unreliable. The shell returned exit code 144 (killed by signal), and sometimes the old process persisted or respawned.

**Root cause:** Same issue as Day 1 — race condition between killing the old uvicorn process and starting a new one. The `pkill` command sometimes kills the shell's own background processes, and uvicorn's child workers can respawn briefly.

**Fix applied:** More careful shutdown sequence:
1. Used `pgrep -f uvicorn` to find exact PIDs
2. Killed specific PIDs with `kill -9`
3. Verified no uvicorn processes remained before starting the new instance
4. Used `sleep 3` to ensure port 8000 was fully released
5. Verified health check before running the scan test

This is a development workflow annoyance, not a code bug. In a real deployment you'd use a process manager (systemd, Docker, etc.).

### No Code Bugs This Session

Unlike Day 1 (where sslyze's API had changed between versions), all new code worked correctly on the first run:
- Crypto mapping lookups returned correct profiles for all 30 findings
- HNDL scoring formula produced expected results
- Severity bucketing thresholds were correct
- Findings were properly sorted by risk score
- All database fields populated correctly

---

## Smoke Test Results

**Target:** google.com
**HNDL context:** S=4 (high data sensitivity), R=4 (long retention)
**Scan time:** ~3 seconds
**Total findings:** 30

**Severity distribution:**

| Bucket | Count | Examples |
|--------|-------|---------|
| **Critical (3)** | 3 | TLS 1.0 (HNDL=80), TLS 1.1 (HNDL=80), TLS_RSA_WITH_3DES_EDE_CBC_SHA (HNDL=80) |
| **High (23)** | 23 | Static RSA cipher suites (HNDL=64), RSA-2048 certs (HNDL=64), ECDHE suites (HNDL=48), RSA-4096 certs (HNDL=48) |
| **Medium (4)** | 4 | TLS 1.3 protocol (HNDL=32), TLS 1.3 cipher suites like TLS_AES_256_GCM_SHA384 (HNDL=32) |
| **Low (0)** | 0 | None — with S=4, R=4, even the best crypto scores 32 (medium) |

**Key observations from the scored results:**
1. **Correct critical identification:** TLS 1.0, TLS 1.1, and RSA+3DES are correctly flagged as the highest priority — they combine deprecated protocols with quantum vulnerability and no forward secrecy.
2. **Correct differentiation between RSA and ECDHE:** Static RSA cipher suites (E=4, HNDL=64) scored higher than ECDHE suites (E=3, HNDL=48) because RSA lacks forward secrecy — breaking one key decrypts all past traffic.
3. **Correct TLS 1.3 handling:** TLS 1.3 suites scored lowest (E=2, HNDL=32) because they mandate forward secrecy and use strong symmetric crypto, even though the ECDHE key exchange is still quantum-vulnerable.
4. **All remediation fields populated:** Every finding has a NIST deadline, PQC replacement recommendation (specific FIPS standard numbers), and actionable migration notes.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `app/services/crypto_mappings.py` | **Created** | Crypto primitive → quantum risk knowledge base |
| `app/services/hndl_scorer.py` | **Created** | HNDL scoring engine (S × R × E formula) |
| `app/routers/scans.py` | **Modified** | Replaced stub scoring with real `score_findings()` call |

---

## What's Next (Day 3)

Core API polish + frontend scaffold:
1. Finalize all REST endpoints (any remaining edge cases)
2. Scaffold the React + Vite frontend
3. Build the scan form component (domain input, S and R sliders)
4. Build the raw findings table component
5. Connect frontend to backend API
