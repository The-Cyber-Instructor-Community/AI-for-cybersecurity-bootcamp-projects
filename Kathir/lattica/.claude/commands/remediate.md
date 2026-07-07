# /remediate — AI Deep Dive on Scan Findings

Analyze scan findings and provide expert PQC remediation guidance. This is the AI remediation
layer — the same analysis a dashboard user would get from the "AI Deep Dive" button, but powered
by your own reasoning instead of an external API.

## Instructions

1. **Determine the target scan:**
   - If the user specifies a scan ID: `/remediate 5` → fetch scan #5
   - If no ID: fetch the most recent scan from `GET /scans/` and use the first result's ID
   - Fetch full results: `curl -s http://localhost:8000/scans/<id>`

2. **Read the Context** — If you haven't already loaded it, Read
   `~/.claude/skills/Agents/LatticaContext.md` for the HNDL model, NIST standards reference,
   and PQC algorithm recommendations.

3. **For each critical and high finding**, provide a deep dive:

   ```
   ── Finding: <value> ──────────────────────────────
   Severity: <CRITICAL|HIGH>    Score: <score>/125 (S<s> × R<r> × E<e>)
   Type: <Protocol|Cipher Suite|Certificate>

   TIER 1 (Deterministic):
     NIST Deadline:    <from scan data>
     PQC Replacement:  <from scan data>
     Migration Notes:  <from scan data>

   TIER 2 (AI Deep Dive):
     Summary:          <1-2 sentence executive summary>
     Risk Explanation: <why this matters for HNDL, considering S and R values>
     Migration Steps:  <numbered, concrete steps with specific tools/libraries/configs>
     Priority:         <timeline tied to NIST deadlines>
   ───────────────────────────────────────────────────
   ```

4. **Migration Steps must be specific.** Name:
   - PQC algorithms: ML-KEM-768, ML-DSA-65, SLH-DSA
   - Libraries: OpenSSL 3.5+, BoringSSL, liboqs, AWS-LC
   - Server config: nginx `ssl_protocols`, `ssl_ciphers`, Apache `SSLProtocol`
   - Testing: hybrid mode deployment, compatibility checks, fallback strategies

5. **After all critical/high findings**, provide an overall assessment:
   - PQC Readiness Grade: Critical / Needs Work / On Track / Strong
   - Top 3 priorities ranked by risk
   - Recommended migration timeline
   - Quick wins (things that can be fixed today)

6. **For medium and low findings**, provide a brief summary table unless the user specifically
   asks for deep dives on them.

## Arguments

$ARGUMENTS will contain optional input:
- A scan ID number: `/remediate 5`
- A specific finding to focus on: `/remediate cipher_suite TLS_RSA_WITH_AES_256_GCM_SHA384`
- Empty: use the most recent scan

User input: $ARGUMENTS
