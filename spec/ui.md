# UI

---

## UI Type

Web app — Next.js 15 + React 19 + Tailwind v4, static export served at `http://localhost:8001/app/` (single origin with the API). Single-page workspace: upload a file, ask questions, read answers with the exact code. The page is **visually complete in Phase 1** — the one working path is real; everything else is a clearly-labelled non-functional stub so the user sees the full vision without mistaking a stub for a bug.

## Views / Screens

### Screen: Analyst Workspace (single page — `frontend/src/app/page.tsx`)

**Purpose:** the user's whole workflow — upload, ask, read the answer + code.

**Layout:**
- **Left sidebar — Dataset Library** *(stub in Phase 1, real in Phase 3)*: in Phase 1 shows a greyed "Dataset library — coming soon" panel. Phase 3: list of persisted datasets, click to select, delete control.
- **Main column — Conversation:**
  - **Upload control** *(real, Phase 1)*: drag/drop or file picker → `POST /datasets`; on success shows the file name, row count, and column chips.
  - **Profile panel** *(stub Phase 1 → real Phase 2)*: "Profile — coming soon" placeholder; Phase 2 shows columns, types, ranges, missing-value counts auto-populated on upload.
  - **Question input** *(real, Phase 1)*: text box + "Ask" button → `POST /analyses`.
  - **Answer block** *(real, Phase 1)*: plain-language answer with the key numbers, plus a **collapsible "Show code" panel** (`<details>`) containing the exact pandas that ran. Also shows `retry_count` if > 0 ("retried N times").
  - **Chart area** *(stub Phase 1 → real Phase 2)*: "Charts — coming soon" placeholder; Phase 2 renders an interactive (hover/zoom) Vega-Lite chart via react-vega.
  - **Follow-up suggestions** *(stub Phase 1 → real Phase 2)*: "Suggested follow-ups — coming soon"; Phase 2 shows 2–3 clickable chips that submit as the next question (carrying context).
  - **Live steps** *(stub Phase 1 → real Phase 3)*: Phase 1 shows a plain spinner; Phase 3 streams "Planning… Running code… Building chart…" via SSE.
- **Top bar:**
  - **Cost meter** *(stub Phase 1 → real Phase 3)*: "Cost: — (coming soon)"; Phase 3 shows per-question tokens/cost + running daily total.
  - **History link** *(stub Phase 1 → real Phase 3)*: "History — coming soon"; Phase 3 opens a browsable audit trail (question, code, result, timestamps).
  - **Add-another-file button** *(disabled stub Phase 1 → real Phase 3)*: enables multi-file join/compare.

**Actions available:**
- Phase 1 (real): upload a file; ask a question; expand/collapse the code panel.
- Phase 2 (real): see auto-profile; view interactive chart; click a follow-up suggestion.
- Phase 3 (real): select/delete library datasets; add a second file and ask cross-file questions; watch live steps; read the cost meter; browse history.

## Error States

- **Upload error** (400): inline red banner with the message (e.g. "Could not parse this CSV").
- **Analysis failed** (422, agent exhausted retries): the answer block shows a clear failure message and still reveals the last code it tried in the collapsible panel ("show what it tried").
- **Network error:** "Network error — is the server running?" banner.
- **Loading:** Phase 1 shows a spinner with "Working…"; Phase 3 replaces it with live streamed steps.
- **Stubs:** every non-functional area is visibly tagged "coming soon" and styled muted/disabled so it is never mistaken for a bug.

## Tech Stack

Next.js 15 + React 19 + Tailwind v4, static export to `frontend/out/`, built with `cd frontend && pnpm build`, served at `:8001/app/`. Charts (Phase 2) via Vega-Lite + react-vega. Tested end-to-end with Playwright under `tests/e2e/`.
