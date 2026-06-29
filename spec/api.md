# API

---

## API Style

REST over HTTP (FastAPI), single origin `http://localhost:8001`. JSON responses wrap data via the existing `ok()` / `api_error()` helpers in `src/api/_common.py` (`{"data": {...}}` on success; `{"detail": {"code","message"}}` on error). The built frontend is served at `/app`. Phase 3 adds a Server-Sent Events stream. All endpoints below are local, unauthenticated (single-user tool).

## Endpoints / Commands

### `POST /datasets`  *(Phase 1)*

**Purpose:** upload a CSV/Excel file; store it locally, load once to extract schema + sample rows (+ profile in Phase 2), create a `datasets` row.

**Request:** `multipart/form-data` with a single `file` field (CSV or .xlsx).

**Response:**
```json
{ "data": {
  "dataset_id": "uuid",
  "name": "sales.csv",
  "file_type": "csv",
  "row_count": 248197,
  "schema": { "order_id": "int64", "region": "object", "amount": "float64" },
  "samples": [ { "order_id": 1, "region": "EU", "amount": 12.5 } ],
  "profile": null
} }
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Unsupported file type, unparseable CSV/Excel, empty file, or file > size limit |
| 500 | Storage/load failure |

### `POST /analyses`  *(Phase 1)*

**Purpose:** ask a question about a dataset; runs the agent (plan → generate_code → execute → retry → finalize) and returns the answer + code.

**Request:**
```json
{ "dataset_id": "uuid", "question": "what is the total revenue?", "dataset_ids": ["uuid"] }
```
(`dataset_ids` optional, Phase 3 multi-file; defaults to `[dataset_id]`.)

**Response:**
```json
{ "data": {
  "analysis_id": "uuid",
  "status": "completed",
  "answer": "Total revenue is $4,812,440.50 across 248,197 orders.",
  "plan": "Sum the amount column over all rows.",
  "code": "result = df['amount'].sum()",
  "result": 4812440.5,
  "retry_count": 0,
  "chart_spec": null,
  "followups": null,
  "tokens": null,
  "estimated_cost_usd": null,
  "error": null
} }
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Missing/blank question, unknown `dataset_id` |
| 422 | Agent exhausted retries / could not produce valid code (status `failed`, `error` populated) |
| 500 | Unexpected internal error |

### `GET /analyses/{analysis_id}`  *(Phase 1)*

**Purpose:** fetch a completed/failed analysis (poll-friendly).
**Response:** same shape as `POST /analyses` data.
**Error cases:** 404 if not found.

### `GET /datasets`  *(Phase 3 — stub-labelled in Phase 1)*

**Purpose:** list persisted datasets for the library sidebar.
**Response:** `{ "data": { "datasets": [ { "dataset_id", "name", "file_type", "row_count", "created_at" } ] } }`

### `GET /datasets/{dataset_id}/profile`  *(Phase 2)*

**Purpose:** fetch the auto-profile (columns, types, ranges, missing values).
**Response:** `{ "data": { "profile": { "amount": {"type":"float64","min":0.1,"max":999.0,"missing":3} } } }`

### `DELETE /datasets/{dataset_id}`  *(Phase 3)*

**Purpose:** remove a dataset and its stored file from the library.
**Response:** `{ "data": { "deleted": true } }`

### `GET /analyses?dataset_id=...`  *(Phase 3 — history audit trail)*

**Purpose:** list past analyses (question, code, result, timestamps, cost) for the history view.
**Response:** `{ "data": { "analyses": [ { "analysis_id", "question", "code", "answer", "status", "created_at", "completed_at", "estimated_cost_usd" } ] } }`

### `GET /cost/daily`  *(Phase 3)*

**Purpose:** running daily total of tokens/cost.
**Response:** `{ "data": { "date": "2026-06-29", "total_tokens": 12044, "total_cost_usd": 0.031 } }`

### `GET /analyses/{analysis_id}/stream`  *(Phase 3 — SSE)*

**Purpose:** live node-status events while the agent works.
**Response:** `text/event-stream`, events: `{"step":"planning"}`, `{"step":"running_code"}`, `{"step":"building_chart"}`, `{"step":"done","analysis_id":"uuid"}`.

## Authentication

None — single-user local tool bound to localhost. No tokens, no accounts.
