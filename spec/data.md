# Data Model

---

## Storage Technology

**SQLite + SQLAlchemy 2.0 + Alembic.** SQLite is the production driver — this is an explicitly single-user, local tool (see `spec/architecture.md` → Stack). DB file at `./data/agent.db` (env `AGENT_DATABASE_URL`). Uploaded data files are stored on local disk under `./data/uploads/`; the DB stores their path + extracted metadata, never the raw rows. The skeleton's `runs` table (`RunRow`) is left in place but unused by this agent; the active tables are `datasets` and `analyses`.

## Entities

### Entity: Dataset

A single uploaded CSV/Excel file plus its extracted, LLM-safe metadata. Persists across days (the dataset library).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | str (uuid) | yes | Primary key |
| name | str | yes | Original filename (display name) |
| file_path | str | yes | Local path to the stored file under `./data/uploads/` |
| file_type | str | yes | `csv` or `xlsx` |
| row_count | int | yes | Total rows (computed locally at load) |
| schema_json | text (JSON) | yes | `{column: dtype}` — LLM-safe schema |
| samples_json | text (JSON) | yes | Bounded sample rows (default 5) used for prompting |
| profile_json | text (JSON) | no | Auto-profile: per-column type, range/min/max, missing counts (Phase 2) |
| size_bytes | int | yes | File size |
| created_at | timestamp (tz) | yes | When uploaded |
| updated_at | timestamp (tz) | yes | Last touched |

### Entity: Analysis

One question→answer run. The browsable audit trail (question, code, result, timestamps, cost).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | str (uuid) | yes | Primary key (= `run_id` in agent state) |
| dataset_id | str (fk → datasets.id) | yes | Primary dataset analysed |
| dataset_ids_json | text (JSON) | no | All datasets for multi-file analyses (Phase 3); defaults to `[dataset_id]` |
| question | text | yes | The user's natural-language question |
| plan | text | no | The agent's natural-language plan |
| code | text | no | The exact pandas code that ran (shown in the collapsible panel) |
| result_json | text (JSON) | no | The computed result (number/table) serialized |
| answer | text | no | Final plain-language answer |
| chart_spec_json | text (JSON) | no | Vega-Lite spec when a chart was produced (Phase 2) |
| followups_json | text (JSON) | no | 2–3 suggested follow-up questions (Phase 2) |
| status | str | yes | `pending` \| `completed` \| `failed` |
| error_message | text | no | Set when `failed` |
| retry_count | int | yes | How many code regenerations occurred (default 0) |
| prompt_tokens | int | no | Gemini usage (Phase 3 cost meter) |
| completion_tokens | int | no | Gemini usage (Phase 3) |
| estimated_cost_usd | float | no | Estimated cost for this analysis (Phase 3) |
| created_at | timestamp (tz) | yes | When asked |
| completed_at | timestamp (tz) | no | When finished |

### Relationships

- `Dataset 1 ──< Analysis` via `analyses.dataset_id`. Multi-file analyses additionally reference datasets via `dataset_ids_json`.
- Conversation context: analyses sharing a `dataset_id` form an ordered thread (by `created_at`); the runner pulls recent turns into `state["messages"]` for follow-ups.

## Data Lifecycle

- **Create:** a `Dataset` on upload (file stored, schema/samples extracted, profile in Phase 2). An `Analysis` row is created (`pending`) when a question is asked, then updated to `completed`/`failed`.
- **Update:** `Dataset.profile_json` set after profiling; `Analysis` filled progressively (plan → code → result → answer → cost).
- **Delete:** the user can delete a dataset from the library (Phase 3) → removes the row and the stored file; its analyses are kept as history (or cascade — see assumption).
- **Retention:** no automatic expiry; everything persists locally until the user deletes it.

> **Assumed:** deleting a dataset keeps its past analyses (they retain `code`/`result` text and remain in history); the dataset link may dangle. No cascade delete of history.

## Sensitive Data

- **Raw rows are the sensitive data** and are NEVER stored in a prompt or sent to the LLM — only `schema_json` + bounded `samples_json` are LLM-visible (the privacy boundary). The full file lives only on local disk.
- No PII handling beyond keeping data local; no secrets stored in the DB. The Gemini API key lives in `.env`, never in the DB.
- `result_json`/`answer` may contain derived values from the data — they stay local in SQLite.
