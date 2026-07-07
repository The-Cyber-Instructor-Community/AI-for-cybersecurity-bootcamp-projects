# /report — Generate a Full PQC Readiness Report

Generate a comprehensive post-quantum cryptography readiness report for a scan. This is the
deliverable — a document the user can share with their team or include in a security assessment.

## Instructions

1. **Determine the target scan:**
   - If the user specifies a scan ID: `/report 5` → fetch scan #5
   - If no ID: fetch the most recent scan from `GET /scans/` and use the first result's ID
   - Fetch full results: `curl -s http://localhost:8000/scans/<id>`

2. **Read the Context** — If you haven't already loaded it, Read
   `~/.claude/skills/Agents/LatticaContext.md` for the HNDL model, NIST standards, and PQC
   algorithm knowledge.

3. **Generate the report** with this structure:

   ```markdown
   # PQC Readiness Report — <domain>
   Generated: <date>
   Scan ID: <id>

   ## Executive Summary
   <2-3 paragraphs summarizing the overall quantum readiness posture, key risks,
   and top recommended actions. Written for a non-technical executive.>

   ## HNDL Risk Parameters
   - Data Sensitivity (S): <value> — <description>
   - Retention Horizon (R): <value> — <description>
   - Scoring Formula: S × R × E = HNDL Risk (1–125)

   ## Findings Overview
   | Severity | Count | Score Range | Action Required |
   |----------|-------|-------------|-----------------|
   | Critical | <n>   | 76–125      | Migrate immediately |
   | High     | <n>   | 36–75       | Plan within 1–2 years |
   | Medium   | <n>   | 11–35       | Include in PQC roadmap |
   | Low      | <n>   | 1–10        | Monitor |

   ## Critical & High Findings — Detailed Analysis
   <For each critical and high finding:>
   ### <finding value>
   - **Type:** <Protocol|Cipher Suite|Certificate>
   - **HNDL Score:** <score>/125 (S<s> × R<r> × E<e>)
   - **NIST Deadline:** <deadline>
   - **PQC Replacement:** <replacement>
   - **Risk Analysis:** <why this matters for HNDL>
   - **Migration Plan:**
     1. <step>
     2. <step>
     3. <step>

   ## Medium & Low Findings — Summary
   <Table listing remaining findings with one-line action items>

   ## Recommended Migration Timeline
   | Phase | Timeframe | Actions |
   |-------|-----------|---------|
   | Immediate | Now | <quick wins — disable deprecated protocols, etc.> |
   | Short-term | 3–6 months | <upgrade cipher suites, enable hybrid PQC> |
   | Medium-term | 6–18 months | <full PQC migration for certificates> |
   | Long-term | 18–36 months | <complete PQC transition, deprecate classical> |

   ## Standards Referenced
   - NIST SP 800-131A Rev 2
   - NIST IR 8547
   - CNSA 2.0
   - FIPS 203 (ML-KEM), FIPS 204 (ML-DSA), FIPS 205 (SLH-DSA)

   ## Overall PQC Readiness Grade: <Critical | Needs Work | On Track | Strong>
   ```

4. **Write the report** to `~/Projects/lattica/reports/<domain>_pqc_report_<date>.md`
   - Create the `reports/` directory if it doesn't exist: `mkdir -p ~/Projects/lattica/reports`
   - Use today's date in the filename: `example.com_pqc_report_2026-07-05.md`

5. **Tell the user** where the report was saved and offer to open it.

## Arguments

$ARGUMENTS will contain optional input:
- A scan ID number: `/report 5`
- Empty: use the most recent scan

User input: $ARGUMENTS
