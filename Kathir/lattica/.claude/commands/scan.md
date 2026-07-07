# /scan — Run a PQC Readiness Scan

Scan a domain's TLS configuration for quantum-vulnerable cryptography using the Lattica backend.

## Instructions

1. **Preflight** — Confirm the Lattica backend is running:
   ```bash
   curl -s http://localhost:8000/health
   ```
   If it's not running, start it:
   ```bash
   cd ~/Projects/lattica/backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
   ```
   Wait a few seconds and retry the health check.

2. **Parse the user's input** from $ARGUMENTS:
   - **If domain + S + R provided** (e.g., `/scan example.com S=5 R=4`): use them directly, skip to step 3.
   - **If only domain provided** (e.g., `/scan example.com`): proceed to step 2a to gather S and R interactively.
   - **If no domain provided** (e.g., `/scan`): ask for the domain first, then proceed to step 2a.

2a. **Gather HNDL parameters interactively** — Present each scale and ask the user to pick:

   **Data Sensitivity (S):**
   ```
   What type of data flows over this connection?

     1 — Public:       Open data, no confidentiality requirement
     2 — Internal:     Internal business data, low sensitivity
     3 — Confidential: Business-sensitive, contractual obligations
     4 — Restricted:   PII, financial data, trade secrets
     5 — Critical:     National security, health records, regulated financial

   Enter 1–5:
   ```

   Wait for the user's answer. Then ask:

   **Retention Horizon (R):**
   ```
   How long must this data stay confidential?

     1 — Ephemeral:    Discarded within days
     2 — Short-term:   6–12 months
     3 — Medium-term:  1–3 years
     4 — Long-term:    3–7 years
     5 — Regulatory:   7+ years (HIPAA, SOX, GDPR, etc.)

   Enter 1–5:
   ```

   Wait for the user's answer before proceeding.

3. **Run the scan** via the Lattica API:
   ```bash
   curl -s -X POST http://localhost:8000/scans/ \
     -H "Content-Type: application/json" \
     -d '{"domain": "<domain>", "data_sensitivity": <S>, "retention_horizon": <R>}'
   ```

4. **Present the results** in a clear, structured format:

   ```
   LATTICA — PQC Readiness Scan
   ═══════════════════════════════
   Target:     <domain>
   Parameters: S=<val> (Data Sensitivity) R=<val> (Retention Horizon)
   Status:     <completed | failed>
   Findings:   <total> total — <crit> critical, <high> high, <med> medium, <low> low
   Peak Risk:  <max score> / 125
   ═══════════════════════════════
   ```

   Then a findings table showing each finding with:
   - Severity (CRITICAL / HIGH / MEDIUM / LOW)
   - Type (Protocol / Cipher Suite / Certificate)
   - Value (the crypto primitive)
   - HNDL Score with formula: S<val> × R<val> × E<val> = <score>
   - NIST Deadline
   - PQC Replacement

5. **If the scan fails**, report the error message and suggest common fixes:
   - DNS resolution failure → check the domain name
   - Connection refused → target might be blocking the scan
   - Timeout → target might be unreachable

6. **After presenting results**, offer to run `/remediate` for a deep dive on any finding.

## Arguments

$ARGUMENTS will contain the user's input after `/scan`. Parse it for:
- The domain name (first argument)
- Optional `S=<1-5>` parameter
- Optional `R=<1-5>` parameter

If S and R are not provided, gather them interactively — do NOT silently default to 3.

User input: $ARGUMENTS
