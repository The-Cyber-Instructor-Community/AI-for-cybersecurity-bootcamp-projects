# Day 4 Runtime Summary — Dashboard UI + Explainability

**Date:** 2026-07-04
**Goal:** Transform the raw findings table into a polished dashboard with visual severity breakdown, at-a-glance stats, finding type filters, HNDL model explainability, and fix duplicate certificate findings from the scanner.

---

## What Was Built

### 1. SeverityChart Component (`components/SeverityChart.tsx`)

A pure SVG donut chart showing severity distribution at a glance. No charting library — built entirely with `stroke-dasharray` and `stroke-dashoffset` on SVG circles.

```
RADIUS = 70, CENTER = 90, STROKE_WIDTH = 28
```

The chart shows:
- **Colored donut segments** — one per severity bucket (critical=red, high=orange, medium=yellow, low=green), sized proportionally to finding counts
- **Center text** — total finding count inside the donut hole
- **Legend** — next to the donut, with colored dots, counts, labels, and descriptions (e.g., "Critical — Migrate immediately")

Segments are rendered by calculating each bucket's fraction of the total, multiplying by the circumference, and using `strokeDasharray` for the visible arc length + `strokeDashoffset` for the rotation offset. A cumulative offset variable tracks where each segment starts.

**Why no charting library:** Keeping dependencies minimal for a 7-day capstone. The donut is ~80 lines of SVG — adding Chart.js or Recharts would be overkill and add ~200KB to the bundle.

### 2. ScanStats Component (`components/ScanStats.tsx`)

Four stat cards displayed in a grid above the findings table:

| Card | Value | Color |
|------|-------|-------|
| Peak HNDL Risk | Highest score found (out of 125) | Color-coded by severity threshold |
| Urgent Findings | Count of critical + high findings | Orange if > 0, green if 0 |
| Total Findings | Total count across all types | Default text color |
| Most Common Type | Dominant finding type + count | Default text color |

CSS grid: `grid-template-columns: repeat(4, 1fr)`, stacks to 2×2 below 900px.

### 3. Finding Type Filter Tabs (`FindingsTable.tsx`)

Horizontal tab bar below the severity chart:

- **All** — shows every finding
- **Protocols** — filters to `finding_type === "protocol"`
- **Cipher Suites** — filters to `finding_type === "cipher_suite"`
- **Certificates** — filters to `finding_type === "certificate"`

Each tab displays its count. Active tab gets accent highlight (`--accent-dim` background + accent border).

### 4. HNDL Model Explainer Panel (`FindingsTable.tsx`)

A togglable "How is this scored?" panel that opens below the scan header. When expanded, it shows:

- **HNDL threat model explanation** — what Harvest Now, Decrypt Later means
- **Formula display** — `S × R × E = HNDL Risk` with color-coded variables (S=indigo, R=purple, E=orange)
- **Factor descriptions** — what each variable measures, plus the user's actual S and R values from the scan
- **Severity thresholds** — what each bucket means and what action to take

This was added because scores like "125" or "60" are meaningless without context. The explainer makes the scoring model transparent and defensible for the capstone evaluation.

### 5. Per-Row Formula Breakdown (`FindingsTable.tsx`)

Each finding row now shows the HNDL formula below the risk score:

```
125
S5 × R5 × E5
```

The S, R, E values are color-coded to match the explainer (S=indigo, R=purple, E=orange). This lets the user see exactly which factors drove each finding's score without expanding the row.

### 6. Wider Layout + Legend Descriptions

- `App.css` max-width increased from 1400px to 1800px to give the dashboard more room
- SeverityChart legend now includes descriptions alongside labels (e.g., "High — Plan migration soon")
- Donut chart sized up: RADIUS=70, STROKE_WIDTH=28 for better visibility

### 7. Certificate Deduplication Fix (Backend)

**Problem:** The scanner was producing ~30 findings for google.com because `_extract_certificate_findings` walked the full certificate chain and created duplicate findings for repeated key types and signature algorithms.

**Fix:** Added a `seen_certs` set in `_extract_certificate_findings` (in `scanner.py`). Before appending a finding, it checks if the cert value (key type+size or signature algorithm) has already been seen. Duplicates are skipped.

**Result:** google.com findings dropped from 30 to 22 — all unique.

---

## Problems Encountered and Fixes Applied

### Problem 1: Duplicate Certificate Findings

**What happened:** Scanning google.com returned 30 findings, many of which were identical certificate entries (e.g., multiple "RSA 2048-bit" from the same chain).

**Root cause:** `_extract_certificate_findings` iterated over every certificate in every deployment's chain without deduplication. A typical cert chain has 2-3 certs, and google.com had multiple deployments, so the same key types and signature algorithms appeared repeatedly.

**Fix applied:** Added a `seen_certs: set()` that tracks cert values (e.g., "RSA 2048-bit", "Signature: sha256WithRSAEncryption"). Only the first occurrence of each value creates a finding.

### Problem 2: Dashboard Lacked Explainability

**What happened:** After the first dashboard build, the user pointed out that a score of "125" is meaningless without context. "What does 125 mean? Is that bad? Out of what?"

**Root cause:** The dashboard showed raw numbers without explaining the scoring model, thresholds, or formula. The HNDL model is the core differentiator — hiding it behind opaque numbers undermines the whole tool.

**Fix applied — four improvements:**
1. **HNDL explainer panel** — togglable "How is this scored?" section with full model explanation
2. **Per-row formula breakdown** — `S5 × R5 × E5` under each score, color-coded
3. **ScanStats cards** — "out of 125" sublabel on the peak risk card
4. **Severity threshold scale** — what each bucket means and the recommended action

### Problem 3: Stat Card Sublabel Text Too Small

**What happened:** The `.stat-sublabel` text (e.g., "critical + high", "out of 125") was barely readable at `0.72rem`.

**Fix applied:** Increased font-size from `0.72rem` to `0.85rem` in `ScanStats.css`.

### Problem 4: Dashboard Didn't Fill Screen Width

**What happened:** The two-column layout had `max-width: 1400px`, leaving unused space on larger monitors.

**Fix applied:** Increased to `max-width: 1800px` in `App.css`.

---

## Design Decisions Made

### Pure SVG over Charting Library
The donut chart uses raw SVG (`stroke-dasharray`/`stroke-dashoffset`) instead of a library like Recharts or Chart.js. For a single donut, the SVG approach is ~80 lines with zero dependencies. Adding a charting library would increase bundle size by ~200KB for marginal benefit.

### Explainability as a First-Class Feature
The HNDL scoring model is the project's differentiator — the user explicitly flagged that raw numbers without context defeat the purpose. The togglable explainer makes the model transparent to both end users and capstone evaluators. The per-row formula breakdown (`S5 × R5 × E5`) makes each score independently verifiable.

### Filter Tabs over Column Sorting
Chose horizontal filter tabs (All / Protocols / Cipher Suites / Certificates) over sortable table columns. Tabs are more intuitive for categorical filtering, and the findings are already sorted by risk (most severe first) from the backend.

### Stat Cards: "How Bad Is It?" at a Glance
The four stat cards answer the most common first questions:
1. "How bad is the worst finding?" → Peak HNDL Risk
2. "How many need immediate attention?" → Urgent Findings (critical + high)
3. "How many total?" → Total Findings
4. "What type of problem do I mostly have?" → Dominant finding type

---

## Files Created/Modified

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/SeverityChart.tsx` | Created | SVG donut chart with legend |
| `frontend/src/components/SeverityChart.css` | Created | Donut chart + legend styling |
| `frontend/src/components/ScanStats.tsx` | Created | Four stat cards (peak risk, urgent, total, dominant type) |
| `frontend/src/components/ScanStats.css` | Created | Stat card grid layout |
| `frontend/src/components/FindingsTable.tsx` | Modified | Added filter tabs, HNDL explainer panel, per-row formula |
| `frontend/src/components/FindingsTable.css` | Modified | Added explainer, filter tab, formula, and severity scale styles |
| `frontend/src/App.css` | Modified | Widened layout from 1400px to 1800px |
| `backend/app/services/scanner.py` | Modified | Certificate deduplication with `seen_certs` set |

---

## Architecture at End of Day 4

```
Browser (localhost:5173)                API (localhost:8000)
┌──────────────────────────────┐       ┌──────────────────────┐
│  React Dashboard (Vite)      │       │  FastAPI Backend      │
│                              │       │                       │
│  ScanForm (sidebar)          │─axios─▶  POST /scans/         │
│  ScanHistory (sidebar)       │       │  GET  /scans/         │
│                              │       │  GET  /scans/{id}     │
│  FindingsTable (main)        │       │  GET  /health          │
│    ├─ HNDL Explainer panel   │       │                       │
│    ├─ SeverityChart (donut)  │       │  sslyze → dedup →     │
│    ├─ ScanStats (4 cards)    │       │  HNDL scorer → SQLite │
│    ├─ Filter tabs            │       └──────────────────────┘
│    └─ Findings table + rows  │
└──────────────────────────────┘
```

---

## What's Next (Day 5)

Agentic remediation layer — Claude API integration:
1. **Tier 1 (deterministic):** Already done — NIST deadlines, PQC replacements, migration notes from the crypto mappings table
2. **Tier 2 (AI-powered):** Per-finding "deep dive" button that sends the finding context to Claude for a detailed, contextual remediation plan — specific to the org's crypto primitive, deployment scenario, and PQC migration path
3. Hybrid API key approach: app-level default key + user-provided override
