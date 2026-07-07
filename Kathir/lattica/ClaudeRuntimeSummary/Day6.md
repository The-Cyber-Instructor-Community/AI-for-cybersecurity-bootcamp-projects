# Day 6 Runtime Summary — Frontend Polish & Interactive Prompting

**Date:** 2026-07-04
**Goal:** Interactive S/R prompting for the terminal agent, frontend polish (domain validation, edge cases, accessibility, responsive improvements), and end-to-end testing of both the dashboard and agent paths.

---

## What Was Built

### 1. Interactive S/R Prompting (Agent + Skills)

Updated both `LatticaContext.md` and `/scan` skill to walk users through each HNDL parameter interactively instead of requiring `S=4 R=3` upfront.

**Before:** User had to say `Scan cloudflare.com S=4 R=3` — requires knowing what S and R mean.

**After:** User says `Scan cloudflare.com` and the agent presents each scale with full descriptions:

```
What type of data flows over this connection?

  1 — Public:       Open data, no confidentiality requirement
  2 — Internal:     Internal business data, low sensitivity
  3 — Confidential: Business-sensitive, contractual obligations
  4 — Restricted:   PII, financial data, trade secrets
  5 — Critical:     National security, health records, regulated financial

Enter 1–5:
```

Then waits for the answer before presenting the Retention Horizon scale. The explicit instruction "Do NOT silently default" prevents the agent from skipping past the user's input.

**Files updated:**
- `~/.claude/skills/Agents/LatticaContext.md` — Step 2 "Gather Parameters" rewritten with Step A (Data Sensitivity) and Step B (Retention Horizon) sub-steps
- `.claude/commands/scan.md` — Step 2a added with both scales and "wait for user's answer" instructions
- `~/Projects/lattica/agent/` copies synced

### 2. Domain Validation (Dashboard)

Updated `ScanForm.tsx` to handle common user mistakes:

- **Auto-stripping:** `https://example.com/path:443` → `example.com` (removes protocol, path, port)
- **Regex validation:** `DOMAIN_RE` validates cleaned input — allows subdomains, rejects empty/garbage
- **Inline error:** Red validation message below the input: "Enter a plain domain like api.example.com"
- **Error clears on typing:** Validation error disappears as soon as the user starts editing

### 3. Zero-Findings Empty State (Dashboard)

Added a guard in `FindingsTable.tsx` for scans that complete but find zero quantum-vulnerable crypto:

```tsx
if (scan.findings.length === 0) {
  return (
    <div className="findings-container">
      <div className="scan-header">
        <h2>{scan.domain}</h2>
        <div className="scan-meta">
          <span>0 findings</span>
          ...
        </div>
      </div>
      <div className="empty-state">
        <h2>No findings</h2>
        <p>No quantum-vulnerable cryptography was detected on {scan.domain}.</p>
      </div>
    </div>
  );
}
```

Previously, a zero-findings scan would render an empty table with headers and no rows.

### 4. Non-Clickable Failed/Pending Scans (Dashboard)

Updated `ScanHistory.tsx` to prevent clicking on non-completed scans:

- Added `non-selectable` class for running/pending/failed scans
- Click handler guards: `scan.status === "completed" && onSelect(scan.id)`
- Visual treatment: `opacity: 0.6`, `cursor: default`, no hover background

Updated `ScanHistory.css`:
- Added `.scan-item.non-selectable` and `.scan-item.non-selectable:hover` styles
- Added `max-height: 380px; overflow-y: auto` on `.scan-list` to prevent sidebar overflow with many scans
- Added heading to empty state: "Scan History" + "No scans yet"

### 5. Accessibility Improvements (Dashboard)

- `ScanForm.tsx`: Added `aria-valuetext` on both slider inputs — screen readers announce "Public — no confidentiality needed" instead of just "1"
- `FindingsTable.tsx`: Added `aria-expanded` on the "How is this scored?" toggle button
- `ScanForm.tsx`: Changed loading button text from "Scanning…" to "Scanning — this takes 5–15 s…" so users know the wait is expected

### 6. Deep Dive Button Guarding (Dashboard)

Added `hasApiKey` prop to `FindingRow`:

- When no API key is configured: button is disabled, text reads "AI Deep Dive — Configure LLM in sidebar first"
- When API key present: button is enabled, text reads "AI Deep Dive — Get Detailed Remediation Plan"
- Ollama users skip the API key requirement (`llmConfig.provider === "ollama"`)

### 7. Error Handling Improvement (App.tsx)

In `handleSelectScan`, added `setActiveScan(null)` in the catch block to clear stale scan data when loading a past scan fails. Previously, the old scan would remain displayed alongside the error banner.

### 8. Severity Badge Fallback (FindingsTable.tsx)

Added fallback color for unknown severity buckets:
```tsx
background: SEVERITY_COLORS[finding.severity_bucket] ?? "#6b7280"
```

Prevents a missing badge color if the backend ever returns an unexpected severity bucket.

### 9. Responsive Breakpoint (App.css)

Changed the sidebar-stacking breakpoint from 800px to 900px. At 800px the sidebar was too compressed — 900px gives more breathing room before switching to stacked layout.

---

## Test Results

### Dashboard Test

- Frontend compiled cleanly: all modules, no errors
- Domain validation working: tested with URLs containing protocols, paths, ports — all cleaned correctly
- Sliders, form submission, scan history all functional
- User confirmed: "Everything seems to be working as intended"

### Agent Test 3: github.com (Interactive S/R)

**Session:** 9e73469a-8738-48ee-a459-db629ee5bfaa

- Agent correctly asked for domain first, then presented S scale, waited for answer (user chose S=1), then presented R scale, waited for answer (user chose R=5)
- Scan executed successfully with the interactively gathered parameters
- Results displayed with correct Tier 1/Tier 2 separation
- **Strong pass** — interactive flow works exactly as designed

---

## Problems Encountered and Fixes Applied

### Problem 1: User Tried to Confirm Backend Separately

**What happened:** I ran `curl -s http://localhost:8000/health` before telling the user to test the agent. User correctly pointed out: "Why are we confirming if the backend is up separately, if the agent will confirm it, itself."

**Fix applied:** None needed — this was a process issue, not a code issue. The agent's preflight step already handles backend health checks. Don't duplicate work the agent is designed to do.

**Lesson:** Trust the agent's procedure. The preflight step exists precisely for this.

### Agent Test 3 Review — Post-Session Improvements

After reviewing the full Test 3 transcript (session `9e73469a`), five improvements were identified and applied to `LatticaContext.md`:

1. **"What if S was higher?" teaser** — When S is low (1 or 2), the agent now shows a sensitivity analysis demonstrating what scores would be at a higher S. Example: "At S=4, these same static RSA suites would score 80/125 (Critical)." Demonstrates the HNDL model's power without requiring a second scan.

2. **"PQC Adoption Status" callout** — Step 4 now requires a prominent callout showing whether any PQC-ready primitives (ML-KEM, hybrid key exchange) were detected. For a PQC readiness tool, the absence of PQC adoption is arguably the headline finding — it shouldn't be buried in a list.

3. **Flag contradictory S/R combinations** — Step 2 now flags unusual pairings like S=1 (public, no confidentiality) + R=5 (must stay confidential 7+ years). The agent asks if the user wants to adjust but doesn't block the scan — the flag is educational, not a gate.

4. **No critical/high fallback** — Step 5 previously said "provide Tier 1/Tier 2 for every critical and high finding." When none exist (as in the S=1 test), the agent adapted correctly but the instruction was ambiguous. Now explicitly codified: "If no critical or high findings exist, apply Tier 1/Tier 2 to the highest-scoring findings regardless of severity bucket."

5. **Preserve cipher suite distinctions when grouping** — The agent had collapsed `TLS_ECDHE_RSA_*` and `TLS_ECDHE_ECDSA_*` into a single `TLS_ECDHE_*` group. The RSA vs ECDSA distinction maps to different certificate chains and migration paths. Step 4 now instructs the agent to group within sub-families, not across them.

A sixth suggestion (mention scan history / offer comparisons) was identified but deferred by user decision.

**Test after applying improvements:** Pass.

---

## Design Decisions Made

### Interactive Prompting over Silent Defaults

The original `/scan` syntax required `S=4 R=3` upfront. Most users won't know what S and R mean on first use. Interactive prompting:
- Educates the user about the HNDL model as they configure it
- Makes the scoring meaningful — you chose these values, not some default
- Still supports the shorthand (`/scan example.com S=4 R=3`) for power users who know the scales

### 15-Item Polish Audit

Rather than one big refactor, Day 6 was a systematic audit of 15 edge cases and UX improvements across both frontend components and the agent. Each fix was small and targeted — no architectural changes, just filling gaps in the existing implementation.

---

## Files Created/Modified

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/ScanForm.tsx` | Modified | Domain validation, auto-stripping, inline error, aria-valuetext, loading text |
| `frontend/src/components/ScanForm.css` | Modified | Added `.validation-error` style |
| `frontend/src/components/FindingsTable.tsx` | Modified | Zero-findings state, severity badge fallback, aria-expanded, Deep Dive button guarding |
| `frontend/src/components/ScanHistory.tsx` | Modified | Non-clickable failed/pending scans, empty state heading |
| `frontend/src/components/ScanHistory.css` | Modified | Non-selectable styles, max-height scroll, empty state heading |
| `frontend/src/App.tsx` | Modified | Clear stale scan on error in handleSelectScan |
| `frontend/src/App.css` | Modified | Responsive breakpoint 800px → 900px |
| `~/.claude/skills/Agents/LatticaContext.md` | Modified | Step 2 interactive S/R prompting + contradictory S/R flag, Step 4 PQC callout + S teaser + grouping rules, Step 5 no-critical fallback |
| `.claude/commands/scan.md` | Modified | Step 2a added with interactive S/R prompting |
| `~/Projects/lattica/agent/` copies | Synced | Updated to match originals |

---

## What's Next (Day 7)

Day 7 is the final day — demo prep and buffer:
1. Write the Day 6 runtime summary ✓
2. Push all changes to GitHub
3. Demo preparation — ensure both paths (dashboard + agent) work end-to-end
4. Final testing pass
5. Any remaining polish from testing
