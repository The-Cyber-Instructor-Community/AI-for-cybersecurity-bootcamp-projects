# Day 3 Runtime Summary — Core API + Frontend Scaffold

**Date:** 2026-07-02
**Goal:** Finalize REST endpoints, scaffold the React frontend with Vite + bun, build the scan form, findings table, and scan history components, connect frontend to backend API, and test the end-to-end flow.

---

## What Was Built

### 1. React Frontend Scaffold

Created `~/Projects/lattica/frontend/` with React 19 + TypeScript + Vite, using **bun** as the package manager (not npm).

```
lattica/frontend/
├── index.html              — Entry HTML, mounts React into #root
├── vite.config.ts          — Vite config with React plugin
├── tsconfig.json           — TypeScript config with JSX support
├── package.json
├── bun.lock
└── src/
    ├── main.tsx            — React entry point (StrictMode + createRoot)
    ├── App.tsx             — Main layout: header, sidebar, main content
    ├── App.css             — Dark theme, two-column layout, CSS variables
    ├── types/
    │   └── index.ts        — TypeScript interfaces mirroring backend Pydantic schemas
    ├── services/
    │   └── api.ts          — Axios client: createScan, listScans, getScan
    └── components/
        ├── ScanForm.tsx    — Domain input + S/R sliders + submit
        ├── ScanForm.css
        ├── FindingsTable.tsx — Scored findings with expandable rows
        ├── FindingsTable.css
        ├── ScanHistory.tsx — Clickable list of past scans
        └── ScanHistory.css
```

### 2. ScanForm Component (`components/ScanForm.tsx`)

Collects three inputs:
- **Domain** — text input for the target (e.g., "api.example.com")
- **Data Sensitivity (S)** — range slider 1–5 with live human-readable labels (e.g., "3 — Confidential — business data")
- **Retention Horizon (R)** — range slider 1–5 with live labels (e.g., "5 — Regulatory — 7+ years")

Shows "Scanning..." loading state while the backend runs sslyze (3–15 seconds). Disables all inputs during scan.

**Why S and R are sliders, not dropdowns:** Sliders give better spatial feedback for an ordinal scale. The user can see and feel "I'm dragging toward the high end" which maps to the risk model intuitively.

### 3. FindingsTable Component (`components/FindingsTable.tsx`)

The main results display. Shows:
- **Scan header** — domain, S/R values, finding count, completion timestamp
- **Severity summary bar** — four colored chips showing counts per bucket (critical/high/medium/low)
- **Findings table** — sortable rows with: severity badge (color-coded), finding type, crypto primitive value, HNDL risk score, crypto exposure score
- **Expandable rows** — click any finding to reveal NIST deadline, PQC replacement, and migration guidance (with a left-accent border for visual distinction)
- **Loading state** — spinner while scan is running
- **Error state** — red-bordered card if scan failed

Findings arrive pre-sorted by HNDL risk (worst first) from the backend.

### 4. ScanHistory Component (`components/ScanHistory.tsx`)

Sidebar list of past scans. Each entry shows:
- Status dot (green=completed, blue=running, yellow=pending, red=failed)
- Domain name
- Timestamp
- S and R values in monospace

Clicking a scan loads its full results into the FindingsTable. Active scan is highlighted with an accent border.

### 5. App Layout (`App.tsx` + `App.css`)

Two-column layout:
- **Left sidebar (340px):** ScanForm on top, ScanHistory below
- **Main area (flex):** FindingsTable or empty state

Dark theme using CSS custom properties:
- `--bg: #0f1117` (background)
- `--surface: #1a1d27` (cards)
- `--accent: #6366f1` (indigo — buttons, active states)

State management is simple `useState` at the App level — no Redux, no context. Props flow down 2 levels max.

Responsive: stacks to single column below 800px.

### 6. API Client (`services/api.ts`)

Three functions wrapping axios calls:
- `createScan(payload)` → `POST /scans/`
- `listScans()` → `GET /scans/`
- `getScan(scanId)` → `GET /scans/{id}`

Base URL hardcoded to `http://localhost:8000`. CORS is already configured on the backend to allow `localhost:5173` (Vite dev server).

### 7. TypeScript Types (`types/index.ts`)

Interfaces mirroring the backend Pydantic schemas: `ScanCreate`, `Finding`, `Scan`, `ScanSummary`. Ensures type safety across the frontend.

---

## Problems Encountered and Fixes Applied

### Problem 1: bun Scaffolded Vanilla TS Instead of React

**What happened:** Running `bun create vite frontend -- --template react-ts` produced a vanilla TypeScript project (plain `main.ts` with DOM manipulation, a `counter.ts` demo file) instead of a React project. No JSX support, no React dependencies.

**Root cause:** The bun `create` command didn't properly pass the `--template react-ts` flag through to Vite's scaffolder, falling back to the default vanilla-ts template.

**Fix applied:**
1. Manually installed React, ReactDOM, and the Vite React plugin: `bun add react react-dom` + `bun add -d @types/react @types/react-dom @vitejs/plugin-react`
2. Created `vite.config.ts` with the React plugin
3. Updated `tsconfig.json` to add `"jsx": "react-jsx"` and `"DOM.Iterable"` to libs
4. Changed `index.html` to point to `main.tsx` instead of `main.ts` and use `#root` div
5. Created `main.tsx` as the React entry point with `createRoot`
6. Removed Vite boilerplate files (`counter.ts`, `style.css`, `assets/`, `main.ts`)

### Problem 2: User Rejected npm — Switched to bun

**What happened:** Initial attempt used `npm create vite@latest` and `npm install`. User stopped the tool call, expressing strong dislike for npm due to recent malicious package incidents.

**Fix applied:** Switched entirely to bun. Used `bun create vite`, `bun add`, `bunx` for all package operations. Saved this as a permanent preference to memory.

### Problem 3: User Questioned React — Considered Vanilla TS

**What happened:** When the React components were being built, the user asked if we could just use TypeScript instead of React. This prompted a design discussion.

**Outcome:** Recommended keeping React because:
- The UI has heavy dynamic state (expandable rows, loading states, scan history with click-to-load)
- Vanilla TS would mean 3x more code for DOM manipulation
- Days 4–6 add more interactivity (charts, AI chat) that React handles much better
- Bootcamp evaluators expect a modern framework

User agreed to proceed with React.

### Problem 4: Recurring Server Restart Race Condition

**What happened:** Same as Days 1 and 2 — `pkill` + restart was unreliable with exit code 144.

**Fix applied:** Same pattern: find PID with `pgrep`, force kill with `kill -9`, wait with `sleep 2`, verify clean before restarting.

### No Build Errors

Once React was properly configured, the entire frontend compiled cleanly on the first `bunx vite build` — 75 modules transformed in 146ms, no errors.

---

## Smoke Test Results

**Backend:** `localhost:8000` — API running, health check passing, scan endpoint returning scored findings
**Frontend:** `localhost:5173` — Vite dev server running, React app compiled and serving

**End-to-end test via API:**
- Scanned google.com with S=4, R=3
- 30 findings returned, all scored
- Distribution: 0 critical, 26 high, 4 medium, 0 low

**User tested in browser:**
- Opened `localhost:8000` — saw `{"detail":"Not Found"}` (expected — this is the API, not the UI)
- Clarified that the UI is at `localhost:5173`

---

## Design Decisions Made

### Package Manager: bun over npm
User preference driven by npm security concerns. All JS tooling now uses bun exclusively.

### Framework: React over vanilla TypeScript
Debated during the session. React won because the UI has too much dynamic state for comfortable vanilla DOM manipulation, especially with the interactive features coming on Days 4–5.

### Styling: Pure CSS with CSS variables, no component library
Dark theme with custom properties. No shadcn/ui, no Ant Design, no Tailwind. Keeps dependencies minimal and gives full control over the look. If Day 4 dashboard work gets heavy, we may reconsider.

### State Management: useState at App level, no Redux
Props flow down at most 2 levels. For 3 components and 4 state variables, this is the right amount of complexity.

---

## Files Created/Modified

| File | Action | Description |
|------|--------|-------------|
| `frontend/vite.config.ts` | Created | Vite config with React plugin |
| `frontend/index.html` | Modified | Updated title, div id, and script source for React |
| `frontend/tsconfig.json` | Modified | Added JSX support and DOM.Iterable |
| `frontend/src/main.tsx` | Created | React entry point |
| `frontend/src/App.tsx` | Created | Main layout with state management |
| `frontend/src/App.css` | Created | Dark theme, two-column layout |
| `frontend/src/types/index.ts` | Created | TypeScript interfaces |
| `frontend/src/services/api.ts` | Created | Axios API client |
| `frontend/src/components/ScanForm.tsx` | Created | Scan form with S/R sliders |
| `frontend/src/components/ScanForm.css` | Created | Form styling |
| `frontend/src/components/FindingsTable.tsx` | Created | Scored findings table with expandable rows |
| `frontend/src/components/FindingsTable.css` | Created | Table styling |
| `frontend/src/components/ScanHistory.tsx` | Created | Past scans list |
| `frontend/src/components/ScanHistory.css` | Created | History list styling |

---

## Architecture at End of Day 3

```
Browser (localhost:5173)          API (localhost:8000)
┌────────────────────┐           ┌──────────────────────┐
│  React App (Vite)  │──axios──▶│  FastAPI Backend      │
│                    │           │                       │
│  ScanForm          │           │  POST /scans/         │
│  FindingsTable     │           │  GET  /scans/         │
│  ScanHistory       │           │  GET  /scans/{id}     │
│                    │           │  GET  /health          │
└────────────────────┘           │                       │
                                 │  sslyze → HNDL scorer │
                                 │  → SQLite             │
                                 └──────────────────────┘
```

---

## What's Next (Day 4)

Dashboard UI enhancements:
1. Risk heatmap or donut chart showing severity distribution
2. Findings sorted/filtered by HNDL score and type
3. Color-coded severity throughout
4. NIST timeline markers
5. Decision on whether to use a charting library or keep it CSS-only
