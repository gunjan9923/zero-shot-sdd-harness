# Architecture

---

## System Overview

A single-user, locally-run data-analysis agent. A browser UI (served from the same FastAPI origin) lets the user upload CSV/Excel files and ask natural-language questions. Each question drives a LangGraph agent that **plans → generates pandas code with Gemini → executes that code locally in a restricted sandbox against the full in-memory DataFrame → inspects the result → retries on failure → finalizes a plain-language answer**. The defining property is the **schema-and-samples-only privacy boundary**: the LLM is given column names, dtypes, and a bounded number of sample rows so it can write code — but the code runs locally on the real data, so answers are computed (never hallucinated) and raw rows never leave the machine. Everything (datasets, analyses, code, results, timestamps, cost) is persisted in a local SQLite database.

## Component Map

```
Browser UI (Next.js static export at :8001/app/)
        │  (fetch / SSE, same origin)
        ▼
FastAPI app (src/api)  ──────────────►  SQLite (datasets, analyses)
        │                                      ▲
        ▼                                      │ persist code/result/cost/timestamps
LangGraph agent (src/graph)                    │
   plan → generate_code → execute_code ────────┘
        │        │              │
        │        ▼              ▼
        │   Gemini API     Execution Sandbox (src/execution)
        │   (schema +        restricted exec of LLM pandas
        │    samples only)   against full DataFrame
        ▼
   reflect/retry → finalize
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| **UI** (`frontend/`) | Upload files, ask questions, render answer + collapsible code; (later) charts, profile, follow-ups, library, cost, streaming, history. |
| **API** (`src/api/`) | HTTP surface: dataset upload/library, ask/analysis, (later) SSE stream + cost/history. Single origin; serves the built frontend at `/app`. |
| **Agent graph** (`src/graph/`) | Orchestrates plan → generate_code → execute_code → reflect/retry → finalize with bounded retries and error handling. |
| **Execution** (`src/execution/`) | Loads files into DataFrames; runs LLM-generated pandas in a restricted sandbox; profiles datasets; extracts schema + samples. |
| **LLM** (`src/llm/`) | Gemini client (already wired) — schema/sample prompts only; usage metadata for cost. |
| **Storage** (`src/db/`) | SQLite via SQLAlchemy 2.0; datasets, analyses, code, results, cost, timestamps; uploaded files on local disk. |

## Data Flow

1. **Trigger:** user uploads a CSV/Excel file in the browser → `POST /datasets` stores the file locally, loads it once to extract schema + sample rows + (later) profile, and creates a `datasets` row.
2. User types a question → `POST /analyses` with `dataset_id` + `question` (+ conversation history) → invokes `run_agent`.
3. **plan** node: Gemini, given schema + sample rows (NOT raw data) + question + prior turns, returns a short natural-language plan.
4. **generate_code** node: Gemini returns a pandas snippet that operates on a provided DataFrame `df` (or `dfs` for multi-file) and assigns its answer to `result`.
5. **execute_code** node: the sandbox runs that snippet against the **full** in-memory DataFrame in a restricted namespace (no network, no fs writes, no dangerous builtins), capturing `result`, stdout, and any exception.
6. **reflect/retry** node: if the code raised, or `result` is empty/all-NaN/unset, route back to **generate_code** with the error context (bounded by `max_retries`); otherwise continue.
7. **finalize** node: Gemini turns the computed `result` (the actual numbers/table) + plan into a plain-language answer.
8. **Output:** the API persists question, plan, generated code, result, answer, timestamps (+ later cost) to `analyses` and returns them; the UI renders the answer and the collapsible code.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Gemini API (`google-genai`) | Plan, code generation, answer phrasing; usage metadata for cost | Retry w/ backoff; on persistent failure set `state.error` → `handle_error` → analysis status `failed`, surfaced in UI. |
| Local filesystem | Store uploaded files + SQLite DB under `./data/` | If a stored file is missing on reload, dataset marked unavailable; user re-uploads. |
| pandas / openpyxl | Load + compute on data locally | Load errors (bad CSV/Excel) → 400 at upload with a clear message. |

## Stack

> Concrete choices for this project. Generic rules (model-naming, DB driver, dev port, real-key tests) live in `harness/patterns/tech-stack.md`.

- **Language:** Python 3.12+ (backend), TypeScript (frontend).
- **Agent framework:** LangGraph (plan-and-execute + reflection/retry loop).
- **LLM provider + model:** Gemini, default `gemini-3.1-pro` (env `AGENT_LLM_MODEL`); auto-detected from `AGENT_GEMINI_API_KEY`. Already wired in `src/llm/providers/gemini.py` — do not add a provider.
- **Backend:** FastAPI (existing `create_app()` factory; serves frontend at `/app`, dev port 8001).
- **Database + ORM:** SQLite + SQLAlchemy 2.0 + Alembic. SQLite is the **production driver** here — this is an explicitly single-user local tool, so tests use SQLite by design (not as a substitute).
- **Frontend:** Next.js 15 + React 19 + Tailwind v4, static export to `frontend/out/`, served at `:8001/app/`.
- **Dependency management:** uv + `pyproject.toml` (Python); pnpm (frontend).

| Key library | Version | Purpose |
|-------------|---------|---------|
| langgraph | (existing) | Agent graph orchestration |
| google-genai | (existing) | Gemini client |
| fastapi / uvicorn | (existing) | HTTP API + server |
| sqlalchemy / alembic | (existing) | ORM + migrations |
| structlog | (existing) | Structured request/response + LLM-payload logging (observability) |
| pandas | ^2.2 | Local data computation |
| openpyxl | ^3.1 | Excel (.xlsx) reading |
| python-multipart | ^0.0.9 | File upload parsing in FastAPI |
| RestrictedPython | ^7.0 | Compile/restrict LLM-generated code before exec (the sandbox) |
| vega-lite / react-vega (frontend) | latest | Interactive charts (Phase 2) |

**Avoid:** any non-Gemini LLM provider; PostgreSQL/Postgres driver (this tool is local SQLite by design); out-of-core/dask engines (in-memory pandas only); sending raw rows to the LLM (privacy boundary); unrestricted `exec`/`eval` of LLM code (use the sandbox); cloud/remote storage.

## Execution Sandbox Design

LLM-generated pandas runs **locally**, so it is treated as untrusted. The sandbox (`src/execution/sandbox.py`):

- **Restricted compile:** compile the snippet with `RestrictedPython` (or an AST allow-list as fallback) — reject `import` of anything outside an allow-list (`pandas`, `numpy`, `math`, `datetime`, `statistics`), reject attribute access to dunders, reject `open`, `exec`, `eval`, `__import__`, `os`, `sys`, `subprocess`.
- **Controlled namespace:** exec runs with a minimal `globals` containing only `pd`, `np`, the loaded DataFrame(s) (`df` / `dfs`), and a curated safe-builtins set; no `open`/`os`/network names are bound.
- **Output contract:** the snippet must assign its answer to a variable named `result`; the sandbox returns `result`, captured stdout, and any exception traceback string.
- **Resource bounds:** a wall-clock timeout (default 25s, env `AGENT_EXEC_TIMEOUT_S`) enforced via a worker thread/process; on timeout the run is treated as a failed attempt and routed to retry/error.
- **No side effects:** no filesystem writes (no `to_csv`/`open`), no network — blocked by the namespace + import allow-list. The DataFrame is read-only by convention; a copy is passed in.

> **Assumed:** RestrictedPython is the primary mechanism; if a needed pandas idiom is over-restricted, the fallback is an AST allow-list walker with the same import/builtin denylist plus a thread-timeout. Either way the denylist (network, fs, os/sys/subprocess, dunders) is the security boundary, not a separate OS sandbox.

## Privacy Boundary (schema-and-samples-only)

The only data ever placed in a Gemini prompt is: column names, inferred dtypes, basic stats (count/min/max for numerics — derived locally), and a bounded number of sample rows (default 5, env `AGENT_SAMPLE_ROWS`). The full dataset is never serialized into a prompt. The structured log records the exact prompt payload so the boundary is auditable (a success criterion in `spec/roadmap.md`). Generated code receives the full DataFrame locally; results returned to the LLM for phrasing in `finalize` are the computed aggregates/tables, not raw rows — and where a result could itself be large, it is truncated before being sent for phrasing.

## Deployment Model

A long-running local process: `uv run python -m src` starts uvicorn on port 8001 serving both the API and the built frontend (`/app`). SQLite DB and uploaded files live under `./data/`. No external services beyond the Gemini API. Single user, bound to localhost.
