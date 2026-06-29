# Roadmap

---

## What This Agent Does

This is a personal, single-user data-analysis agent with a browser UI. The user uploads CSV/Excel files and asks questions in plain English ("what's the average order value by region?", "now break that down by month"). The agent behaves as a **code-executing analyst**: for each question it plans an approach, writes real pandas/Python, executes that code locally against the actual loaded data, inspects the result, and retries with a different approach if the code errors or the result looks wrong. It returns trustworthy answers — plain-language prose with the key numbers, summary tables, and (in later phases) interactive charts. Its privacy model is **schema-and-samples-only**: the LLM only ever sees column names, dtypes, and a few sample rows in order to write code; the full dataset is processed locally and raw rows never leave the machine.

## Who Uses It

A single technical-ish individual (analyst, founder, ops person, researcher) running the agent locally on their own machine. They have one or more data files and a stream of ad-hoc questions, and they want trustworthy answers without writing the pandas themselves. They value transparency (seeing the exact code that produced the number) and privacy (raw data stays local).

## Core Problem Being Solved

Answering ad-hoc questions about a spreadsheet today means either (a) writing pandas/SQL by hand for every question, or (b) pasting data into a cloud LLM that hallucinates numbers and leaks the raw rows. This agent removes both: it writes and *actually runs* the analysis code on the real local data (so the numbers are real, not hallucinated), and it only sends schema + a few sample rows to the LLM (so raw data never leaves the machine).

## Success Criteria

- [ ] User uploads a CSV and asks a question; the agent returns a plain-language answer whose numbers exactly match a hand-computed pandas result on the full file (not a sampled subset).
- [ ] The exact code that produced the answer is shown to the user in a collapsible panel and is runnable as-is.
- [ ] When the first generated code raises an exception, the agent automatically retries with corrected code (up to a bounded retry count) and still returns a correct answer.
- [ ] Only column names, dtypes, and a bounded number of sample rows are ever sent to the LLM — verifiable from the structured logs of the LLM request payload.
- [ ] A ~100MB CSV question returns within ~30s on the tested path.

## What This Agent Does NOT Do (Out of Scope)

- No multi-user / accounts / auth — it is a single-user local tool bound to `localhost`.
- No cloud deployment, no remote data sources (databases, S3, APIs) — local files only.
- No write-back / editing of the source data — read-only analysis.
- No model fine-tuning or training; no non-Gemini providers wired (Gemini only).
- No arbitrary network/filesystem access from generated code — the execution sandbox blocks it.
- No automated scheduled runs — every analysis is user-triggered.

## Key Constraints

- **Provider:** Gemini only (`AGENT_GEMINI_API_KEY`, already set in the skeleton). Default model `gemini-3.1-pro`, env-configurable via `AGENT_LLM_MODEL`.
- **Stack:** Python + FastAPI + LangGraph + SQLite + pandas; Next.js 15 static-export frontend served at `:8001/app/`.
- **Access:** browser web UI, single origin `http://localhost:8001`.
- **Privacy:** schema-and-samples-only to the LLM; raw rows never sent.
- **Security:** LLM-generated pandas runs locally in a restricted execution sandbox (no network, no filesystem writes outside a temp scratch, no dangerous builtins).
- **Files:** medium-sized, up to ~100MB; answers within ~30s.
- **Cost:** cost-conscious — minimize tokens (schema + bounded samples only), surface estimated cost/tokens per question (later phase).

> **Assumed:** files up to ~100MB are loaded fully into an in-memory pandas DataFrame (a ~100MB CSV is comfortable in RAM on a typical dev machine). No chunked/out-of-core engine in scope.
> **Assumed:** "result looks wrong" detection in Phase 1 is limited to: code raised an exception, returned an empty/all-NaN result, or returned nothing assigned to `result`. Richer semantic self-critique is deferred to the reflection upgrade phase.

## Phases of Development

> **Phase 1 is the smallest first-time-right user-testable win.** Backend is REAL on the one core path (upload one CSV → ask one question → plan → write + run pandas locally → answer + code). Frontend is visually complete: real upload+ask+answer UI plus clearly-labelled NON-FUNCTIONAL stubs for charts, multi-file, dataset library, cost meter, auto-profiling, follow-up suggestions, streaming, and history.

### Phase 1 — Upload → Ask → Code-Executed Answer

- **Goal:** The user uploads one CSV, types one question, and gets back a correct plain-language answer plus the exact pandas code that produced it (in a collapsible panel). The agent really plans, generates code via Gemini (schema + samples only), executes it locally in a restricted sandbox against the full DataFrame, and auto-retries on code error. All later features appear as clearly-labelled non-functional stubs.
- **Independent slices (parallel build units):**
  - `db-migration` (backend) — adds `datasets` and `analyses` tables and the first Alembic migration `0001`. Deps: none.
  - `sandbox` (backend) — the restricted local pandas execution sandbox module (`src/execution/sandbox.py`) + dataset loader (`src/execution/loader.py`). Deps: none.
  - `agent-graph` (backend) — extends `AgentState` and the LangGraph nodes (plan → generate_code → execute_code → reflect/retry → finalize → handle_error), prompts, and runner. Deps: `sandbox` (calls the sandbox), `db-migration` (writes `analyses`). Serializes after those two.
  - `api-routes` (backend) — upload, ask, get-analysis endpoints (`src/api/datasets.py`, `src/api/analyses.py`) + domain models. Deps: `agent-graph` (invokes the runner), `db-migration`. Serializes after those.
  - `frontend` (frontend) — real upload + ask + answer + collapsible-code UI in `frontend/src/app/page.tsx` and components; labelled stubs for charts/multi-file/library/cost/profiling/suggestions/streaming/history. Deps: none (codes against the documented API contract in `spec/api.md`).
  - `e2e` (test) — Playwright smoke test under `tests/e2e/` for the upload→ask→answer journey. Deps: `frontend`, `api-routes`.
- **Key surfaces / files:**
  - `db-migration`: `src/db/models.py` (add `DatasetRow`, `AnalysisRow`), `alembic/versions/0001_datasets_analyses.py`
  - `sandbox`: `src/execution/sandbox.py`, `src/execution/loader.py`
  - `agent-graph`: `src/graph/state.py`, `src/graph/nodes.py`, `src/graph/edges.py`, `src/graph/agent.py`, `src/graph/runner.py`, `src/prompts/plan.md`, `src/prompts/generate_code.md`
  - `api-routes`: `src/api/datasets.py`, `src/api/analyses.py`, `src/api/__init__.py` (mount routers), `src/domain/dataset.py`, `src/domain/analysis.py`
  - `frontend`: `frontend/src/app/page.tsx`, `frontend/src/components/*`
  - `e2e`: `tests/e2e/upload_ask.spec.ts`, `playwright.config.ts`
- **Gate command:** `uv run alembic upgrade head && uv run pytest tests/phase1 -q && (cd frontend && pnpm build) && uv run pytest tests/e2e -q`
  - The backend test in `tests/phase1` uploads a real fixture CSV **large enough (≥ 200k rows)** that a sampled answer and a full-data answer differ, calls the real Gemini API via `.env`, runs the generated pandas in the sandbox, and asserts the returned number equals the full-data pandas computation (not the sample). SQLite is the production driver here (single-user local tool), so tests use SQLite by design.
- **How the user tests it (handoff seed):**
  1. Ensure `.env` has `AGENT_GEMINI_API_KEY` set.
  2. `cd frontend && pnpm build` then from the repo root `uv run alembic upgrade head` and `uv run python -m src`.
  3. Open `http://localhost:8001/app/`.
  4. Upload a CSV (e.g. a sales export), type a question like "what is the total revenue?" and submit.
  5. Expected: a streaming-free spinner, then a plain-language answer with the number, and an expandable "Show code" panel containing the exact pandas that ran. The answer's number matches the file.
  6. **Labelled stubs (not bugs):** a greyed-out "Charts (coming soon)" area, a disabled "Add another file" button, a "Dataset library — coming soon" sidebar, a "Cost: — (coming soon)" meter, a "Profile — coming soon" panel, a "Suggested follow-ups — coming soon" block, and a "History — coming soon" link. All visibly tagged.

### Phase 2 — Insight Layer: Profiling + Charts + Follow-up Suggestions

- **Goal:** Turn the analyst's output production-grade. On upload the agent auto-profiles the dataset (columns, types, ranges, missing values); each answer can include an interactive (zoom/hover) chart with an auto-picked chart type; and after each answer the agent suggests 2–3 follow-up questions the user can click. Conversation history is carried so follow-ups like "now break that down by region" work in context.
- **Capabilities delivered (≥3):** `auto_profile_dataset`, `render_chart`, `suggest_followups`, `conversational_followup`.
- **Independent slices (parallel build units):**
  - `profiling` (backend) — `profile` node + `src/execution/profiler.py`; writes a profile JSON to `datasets`. Deps: none (extends existing graph/loader).
  - `charting` (backend) — chart-spec generation node + `src/charts/spec.py` (agent emits a Vega-Lite spec; data computed locally, embedded). Deps: none.
  - `followups` (backend) — `suggest_followups` node + conversation-history threading in `AgentState.messages`/runner. Deps: none.
  - `frontend-insight` (frontend) — wire the profiling panel, the interactive chart renderer (Vega-Lite via react-vega), and clickable follow-up chips; remove their "coming soon" labels. Deps: none (against the API contract).
- **Key surfaces / files:** `src/execution/profiler.py`, `src/charts/spec.py`, new nodes in `src/graph/nodes.py`, `src/prompts/chart.md`, `src/prompts/followups.md`, `src/api/datasets.py` (profile endpoint), `frontend/src/components/Profile.tsx`, `frontend/src/components/Chart.tsx`, `frontend/src/components/Followups.tsx`.
- **Gate command:** `uv run pytest tests/phase2 -q && (cd frontend && pnpm build) && uv run pytest tests/e2e -q`
  - Asserts (real Gemini): uploading a fixture produces a profile with correct dtypes and missing-value counts; a question that warrants a chart returns a valid Vega-Lite spec with locally-computed data; each answer returns 2–3 non-empty follow-up suggestions; a follow-up question referencing "that" resolves using prior-turn context.
- **How the user tests it (handoff seed):** Upload a CSV → see the profile panel populate automatically. Ask a question that warrants a chart → see prose + an interactive chart you can hover/zoom + 2–3 follow-up chips. Click a follow-up like "break that down by region" → get a contextual answer. (Multi-file, dataset library, cost meter, streaming, history remain labelled stubs.)

### Phase 3 — Workspace Layer: Multi-file Join + Dataset Library + Cost Meter + Streaming + Audit History

- **Goal:** Make it a persistent workspace. The user can load multiple files and ask questions that join/compare them; uploaded datasets persist across days in a browsable local library; each question shows estimated cost + tokens with a running daily total; live step updates stream while the agent works ("Planning… Running code… Building chart…"); and the full run history (question, code, result, timestamps) is a browsable audit trail.
- **Capabilities delivered (≥3):** `multi_file_analysis`, `dataset_library`, `cost_tracking`, `stream_progress`, `run_history`.
- **Independent slices (parallel build units):**
  - `multi-file` (backend) — multi-DataFrame loading + schema/sample bundling for N files; plan/generate_code prompts updated for joins. Deps: none.
  - `library` (backend) — list/select/delete dataset endpoints + persistence of uploaded files to a local store. Deps: none.
  - `cost` (backend) — token/cost estimation from Gemini usage metadata, persisted per analysis + daily aggregate endpoint. Deps: none.
  - `streaming` (backend) — Server-Sent Events progress stream from the graph (`src/api/stream.py`, node-level status emits). Deps: none.
  - `frontend-workspace` (frontend) — multi-file picker, dataset library sidebar, cost meter, live step display, history view; remove remaining "coming soon" labels. Deps: none (against the API contract).
- **Key surfaces / files:** `src/execution/loader.py` (multi-file), `src/api/datasets.py` (library CRUD), `src/api/stream.py`, `src/api/analyses.py` (history + daily cost), `src/db/models.py` (cost columns), `alembic/versions/0002_cost_columns.py`, `frontend/src/components/Library.tsx`, `frontend/src/components/CostMeter.tsx`, `frontend/src/components/Steps.tsx`, `frontend/src/components/History.tsx`.
- **Gate command:** `uv run alembic upgrade head && uv run pytest tests/phase3 -q && (cd frontend && pnpm build) && uv run pytest tests/e2e -q`
  - Asserts (real Gemini): a question across two fixture files returns a joined result matching a hand-computed join; datasets persist and are listable after a fresh app start; an analysis records non-zero token/cost from Gemini usage metadata and the daily total aggregates them; the SSE stream emits ordered node-status events; the history endpoint returns prior analyses with code + result + timestamps.
- **How the user tests it (handoff seed):** Upload two files, ask a cross-file question → get a joined answer. Restart the app → both files still appear in the library sidebar; click one to reload it. Ask a question → watch live "Planning… Running code…" steps and see the cost/tokens for that question plus the running daily total. Open History → browse past questions with their code and results. No stubs remain.
