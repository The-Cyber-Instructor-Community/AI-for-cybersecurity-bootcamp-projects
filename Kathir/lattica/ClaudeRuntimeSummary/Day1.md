# Day 1 Runtime Summary — Scaffold + Scanner Integration

**Date:** 2026-07-01
**Goal:** Stand up the project skeleton, integrate sslyze as the TLS scanning engine, define database models, wire up initial API endpoints, and prove the pipeline works end-to-end with a real domain scan.

---

## What Was Built

### 1. Project Structure

Created the full backend scaffold under `~/Projects/lattica/backend/`:

```
lattica/backend/
├── .env                  — Local environment config (API key, DB path)
├── .env.example          — Template for other developers
├── .gitignore            — Keeps .env and .db files out of git
├── requirements.txt      — All Python dependencies pinned
└── app/
    ├── __init__.py
    ├── main.py            — FastAPI entry point
    ├── core/
    │   ├── __init__.py
    │   ├── config.py      — Loads settings from .env
    │   └── database.py    — Async SQLAlchemy engine + session factory
    ├── models/
    │   ├── __init__.py
    │   ├── scan.py        — Scan and Finding ORM models
    │   └── schemas.py     — Pydantic request/response schemas
    ├── routers/
    │   ├── __init__.py
    │   └── scans.py       — API endpoint handlers
    └── services/
        ├── __init__.py
        └── scanner.py     — sslyze wrapper
```

**Why this structure:** Separating concerns early (routers vs services vs models vs core) keeps the codebase navigable as it grows over the week. The `services/` layer is where the sslyze wrapper and (later) the HNDL scoring engine and Claude remediation layer will live. The `core/` layer holds cross-cutting infrastructure (config, database). This way, routers stay thin — they just validate input, call a service, and return the result.

### 2. Configuration System (`app/core/config.py`)

A `Settings` class that reads from environment variables via `python-dotenv`. Key design decision here: the Anthropic API key is loaded as a **default** that can be overridden per-request. This supports two usage modes:
- **Demo mode:** App owner's API key in `.env`, everything just works
- **Self-hosted mode:** Users paste their own API key into the UI settings

This came out of a design discussion where we decided against requiring the Claude API key as the only option — users should be able to use their own keys without the app owner paying for all usage.

### 3. Database Layer (`app/core/database.py`)

Async SQLAlchemy with SQLite via `aiosqlite`. We went async because sslyze scans take 2–15 seconds, and we don't want to block the event loop for other requests while one scan is running. The scan itself runs in a thread pool (`asyncio.to_thread`), but the database layer being async means multiple requests can be served concurrently.

Tables are auto-created on startup via `init_db()` called from FastAPI's `on_event("startup")` hook. No migration tool (like Alembic) — unnecessary complexity for a 7-day project.

### 4. Data Models (`app/models/scan.py` and `app/models/schemas.py`)

**ORM models (scan.py):**
- `Scan` — represents one TLS scan of a target domain. Holds the user-provided HNDL context: `data_sensitivity` (1–5) and `retention_horizon` (1–5). Tracks scan lifecycle via `ScanStatus` enum (pending → running → completed/failed).
- `Finding` — one crypto finding within a scan. Types: cipher_suite, protocol, certificate, key_exchange. Each finding carries a `crypto_exposure_score` (auto-derived from the crypto primitive), and a composite `hndl_risk_score` (S × R × E). Also has fields for `nist_deadline`, `pqc_replacement`, and `migration_notes` — these are populated by the scoring engine (Day 2) and remediation layer (Day 5).

**Why separate Pydantic schemas (schemas.py):** The ORM models define the database shape; the Pydantic schemas define the API contract. This prevents leaking internal fields to the client and lets us evolve the API independently from the storage layer. Three schemas: `ScanCreate` (input), `ScanResponse` (full output with findings), `ScanSummary` (lightweight list view without findings).

### 5. sslyze Scanner Wrapper (`app/services/scanner.py`)

The core integration piece. Takes a domain string, runs sslyze against it, and returns a list of `RawFinding` dataclass objects. Three extractors:

- **`_extract_protocol_findings`** — checks which TLS/SSL versions (SSL 2.0 through TLS 1.3) the server accepts
- **`_extract_cipher_findings`** — lists individual cipher suites accepted across all protocol versions, deduplicating across versions
- **`_extract_certificate_findings`** — walks the certificate chain to extract key types (RSA, ECDSA, Ed25519), key sizes, and signature algorithms

The scan runs in a thread pool (`asyncio.to_thread`) because sslyze is synchronous and does blocking network I/O.

### 6. API Endpoints (`app/routers/scans.py`)

Three endpoints:

| Method | Path | What it does |
|--------|------|-------------|
| POST | /scans/ | Creates a scan record, runs sslyze, stores findings, returns full result |
| GET | /scans/ | Lists all scans (summary view, no findings), most recent first |
| GET | /scans/{id} | Returns a single scan with all its findings |

Design note: scans run **synchronously within the request** — the POST doesn't return until the scan is done. For a production tool we'd use a task queue (Celery, etc.), but for the demo this keeps things simple. Typical scan time is 2–5 seconds, which is acceptable for a demo.

---

## Problems Encountered and Fixes Applied

### Problem 1: sslyze 6.x API Breaking Change

**What happened:** The initial scanner code was written using the `result.scan_result.for_scan_command(ScanCommand.XXX)` API pattern, which was the correct approach for sslyze 5.x. When we ran the first scan against google.com, the server returned `Internal Server Error`.

**Error from server logs:**
```
AttributeError: 'AllScanCommandsAttempts' object has no attribute 'for_scan_command'
```

**Root cause:** sslyze 6.x changed its result access pattern. Instead of a `for_scan_command()` method that takes a `ScanCommand` enum, results are now accessed as **direct attributes** on the `scan_result` object, each returning an "attempt" object with a `.result` property.

**Old API (5.x — what we wrote first):**
```python
cmd_result = result.scan_result.for_scan_command(ScanCommand.TLS_1_2_CIPHER_SUITES)
for cipher in cmd_result.accepted_cipher_suites:
    ...
```

**New API (6.x — what actually works):**
```python
attempt = result.scan_result.tls_1_2_cipher_suites  # direct attribute access
if attempt.result:  # .result is None if scan wasn't run
    for cipher in attempt.result.accepted_cipher_suites:
        ...
```

**How we diagnosed it:** Ran a Python introspection script that:
1. Created a minimal scan against google.com with just `TLS_1_2_CIPHER_SUITES`
2. Printed the type of `scan_result` → `AllScanCommandsAttempts`
3. Printed `dir(scan_result)` to see available attributes → revealed `ssl_2_0_cipher_suites`, `tls_1_2_cipher_suites`, etc. as direct attributes
4. Accessed `tls_1_2_cipher_suites.result.accepted_cipher_suites` → confirmed it works

**Fix applied:** Rewrote all three extractor functions:
- `_extract_protocol_findings`: Changed from `for_scan_command()` lookup to `getattr(result.scan_result, attr_name)` with string attribute names
- `_extract_cipher_findings`: Same pattern — iterate over attribute name strings instead of `ScanCommand` enums
- `_extract_certificate_findings`: Changed `for_scan_command(ScanCommand.CERTIFICATE_INFO)` to `result.scan_result.certificate_info.result`

All three extractors also added `attempt.result` null checks since the attempt object exists even if the scan command wasn't actually run (`.result` will be `None` in that case).

### Problem 2: Server Restart Flakiness

**What happened:** After applying the sslyze API fix, restarting the server via `pkill` + background launch was unreliable. Multiple attempts to kill the old process and start a new one resulted in `exit code 144` (process killed by signal) and the health check failing.

**Root cause:** Race condition between killing the old uvicorn process and starting a new one. The old process wasn't fully dead before the new one tried to bind to port 8000, and the shell script was getting caught in the signal handling.

**Fixes that didn't fully work:**
- `pkill -f "uvicorn app.main:app"` followed by `sleep 1` — the kill signal propagation wasn't complete before the new process started
- `nohup` background launch — same issue

**Fix that worked:**
1. Killed the old process by PID directly
2. Used a longer `sleep 2` gap
3. Bound to `127.0.0.1` instead of `0.0.0.0` (simpler for local testing)
4. Verified with health check before proceeding to the scan test

This is not a code bug — it's a local development workflow issue that won't affect the actual application.

---

## Smoke Test Results

**Target:** google.com
**Scan time:** ~2.5 seconds
**Total findings:** 30

**Breakdown:**
- **4 protocol findings:** TLS 1.0, TLS 1.1, TLS 1.2, TLS 1.3
  - Notable: Google still accepts TLS 1.0 and 1.1 (both deprecated, both quantum-vulnerable)
- **14 cipher suite findings:** Mix of RSA key exchange, ECDHE-RSA, ECDHE-ECDSA, and TLS 1.3 suites
  - Quantum-vulnerable: All RSA and ECDHE key exchanges
  - TLS 1.3 suites (TLS_AES_256_GCM, TLS_CHACHA20_POLY1305) use ephemeral key exchange but still with classical ECDHE
- **12 certificate findings:**
  - ECDSA-256 leaf cert, RSA-2048 and RSA-4096 intermediates
  - All signatures use sha256WithRSAEncryption
  - All of these are quantum-vulnerable (Shor's algorithm breaks both RSA and ECC)

**All three API endpoints verified working:**
- `POST /scans/` → creates scan, runs sslyze, returns findings (201)
- `GET /scans/` → lists all scans in reverse chronological order
- `GET /scans/3` → returns full scan with 30 findings

**State at end of Day 1:** HNDL scores are all stubbed at 0.0 and severity buckets defaulted to "medium". The `nist_deadline`, `pqc_replacement`, and `migration_notes` fields are all null. These will be populated by the HNDL scoring engine on Day 2.

---

## What's Next (Day 2)

Build the HNDL scoring engine:
1. Crypto exposure mapping — a lookup table from cipher suite / key type / protocol → quantum risk score (1–5)
2. Composite HNDL calculation — S × R × E with severity bucketing
3. NIST deadline and PQC replacement mapping (deterministic Tier 1 guidance)
4. Wire it into the scan pipeline so findings come back fully scored
