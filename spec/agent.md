# Agent

> LangGraph project — this file is REQUIRED and complete.

---

## Agent Architecture Pattern

**Chosen:** **Graph (LangGraph) — plan-and-execute + reflection/retry.** Each question is a multi-step pipeline with a conditional retry loop (regenerate code when execution fails), which is exactly what conditional edges + a bounded loop counter in state model cleanly. A single deterministic tool-loop is too weak (no explicit plan, no reflection); multi-agent/supervisor is overkill for one analyst flow.

The Phase-1 graph wires the **full loop real** on the single-file, single-question path. Later phases extend nodes (profiling, charting, follow-ups, multi-file, cost, streaming) without changing the topology's spine.

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| plan | Gemini | `gemini-3.1-pro` (env `AGENT_LLM_MODEL`) | Needs reasoning over schema to choose an approach; quality over latency. |
| generate_code | Gemini | `gemini-3.1-pro` | Code correctness is the highest-stakes step. |
| finalize (answer phrasing) | Gemini | `gemini-3.1-pro` | Turns computed numbers into clear prose; could later drop to a cheaper model. |

> **Assumed:** all nodes use the single configured model in Phase 1 (one `LLMClient`); a per-node model split (cheaper model for phrasing) is a later cost optimization, not a Phase-1 concern. `gemini-3.1-pro` is the wired skeleton default.

**Fallback behaviour:** each Gemini call is wrapped with bounded retry + exponential backoff for transient/rate-limit errors. On persistent failure a node sets `state["error"]` and the graph routes to `handle_error`, which records the analysis as `failed` and surfaces the message in the UI. No offline/stub path — tests call the real Gemini API with keys from `.env`.

**Prompt strategy:** system/user split, prompts loaded from `src/prompts/*.md`. `generate_code` requests a single pandas snippet that operates on `df` (or `dfs`) and assigns to `result` (structured contract enforced by extraction + the sandbox output contract). Inputs to every prompt are **schema + sample rows only**, never raw data.

---

## Tools & Tool Calling

This agent's "tool" is the **local code executor**, invoked deterministically by the `execute_code` node (not chosen by the LLM). The LLM produces code; the graph runs it.

| Tool name | Description | Inputs | Output | Side-effects |
|-----------|-------------|--------|--------|--------------|
| `run_pandas` (sandbox) | Execute LLM-generated pandas in a restricted namespace against the full DataFrame(s) | `code: str`, `df`/`dfs` | `{result, stdout, error}` | None (no fs/network; read-only DataFrame copy) |
| `load_dataset` (loader) | Load a CSV/Excel file into a DataFrame; extract schema + samples | `file_path` | `DataFrame`, schema, samples | Reads local file |

**Tool selection strategy:** rule-based — the graph always calls the sandbox at `execute_code`; the LLM never decides which tool to call.

**Tool failure handling:** a sandbox exception/timeout is captured (not raised) and fed back via `reflect/retry`; bounded by `max_retries`, after which the graph routes to `handle_error`.

---

## Agent State

```python
class AgentState(TypedDict, total=False):
    # Identity
    run_id: str                       # analysis id, set at initialisation
    dataset_id: str                   # the dataset being analysed
    dataset_ids: list[str]            # multi-file (Phase 3); single-element in Phase 1

    # Input
    question: str                     # the user's natural-language question
    messages: list                    # prior chat turns [{role, content}] for follow-up context

    # Schema/sample context (privacy boundary — what the LLM may see)
    schema: dict                      # {column: dtype, ...} per dataset
    samples: list                     # bounded sample rows per dataset (default 5)

    # Pipeline data (populated progressively by nodes)
    plan: str                         # natural-language approach (plan node)
    code: str                         # generated pandas snippet (generate_code node)
    exec_result: object | None        # value of `result` from the sandbox (execute_code)
    exec_stdout: str | None           # captured stdout
    exec_error: str | None            # sandbox exception/timeout text (drives retry)
    retry_count: int                  # incremented each regenerate; bounded by max_retries
    max_retries: int                  # default 2 (env AGENT_MAX_RETRIES)

    # Output
    answer: str                       # final plain-language answer (finalize node)
    status: str                       # "completed" | "failed"

    # Control
    error: str | None                 # fatal error → handle_error
```

> The skeleton `AgentState` already has `run_id`, `messages`, `error`; this extends it (do not restructure).

---

## Nodes / Steps

### `plan`
**Reads from state:** `question`, `schema`, `samples`, `messages`
**Writes to state:** `plan`, (on failure) `error`
**LLM call:** yes — Gemini, `src/prompts/plan.md`; input is schema + samples + question + prior turns; output is a short plan string.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini | plan generation | retry/backoff; persistent → set `error` |
**Behaviour:** decides the analytical approach (which columns, what aggregation) in natural language so the next node can write targeted code.

### `generate_code`
**Reads from state:** `question`, `schema`, `samples`, `plan`, `exec_error` (if retrying), `code` (prior attempt)
**Writes to state:** `code`, (on failure) `error`
**LLM call:** yes — Gemini, `src/prompts/generate_code.md`; on retry the prior code + error are included so the model corrects itself; output is a pandas snippet assigning `result`.
**Behaviour:** produces the executable analysis code against `df`/`dfs`; the snippet is extracted (fenced block) before exec.

### `execute_code`
**Reads from state:** `code`, `dataset_id`/`dataset_ids`
**Writes to state:** `exec_result`, `exec_stdout`, `exec_error`
**LLM call:** no.
**External calls:**
| System | Operation | On Failure |
|--------|-----------|------------|
| Sandbox | run pandas vs full DataFrame | capture exception/timeout into `exec_error` (not fatal — drives retry) |
**Behaviour:** loads the DataFrame(s) (cached per session/dataset) and runs the snippet in the restricted sandbox; captures `result`, stdout, error.

### `reflect` (router function `after_execute`)
**Reads from state:** `exec_error`, `exec_result`, `retry_count`, `max_retries`
**Writes to state:** `retry_count` (incremented when routing back)
**LLM call:** no (Phase 1 — heuristic). Routes to `generate_code` if `exec_error` set OR `exec_result` is None/empty/all-NaN and `retry_count < max_retries`; to `handle_error` if retries exhausted with an error; otherwise to `finalize`.
**Behaviour:** the reflection/retry decision. (A later phase may add an LLM self-critique here.)

### `finalize`
**Reads from state:** `question`, `plan`, `exec_result`, `exec_stdout`
**Writes to state:** `answer`, `status="completed"`
**LLM call:** yes — Gemini; turns the computed `result` (truncated if large) into plain-language prose with the key numbers.
**Behaviour:** composes the trustworthy answer from real computed values.

### `handle_error`
**Reads from state:** `error` (or exhausted `exec_error`), `run_id`
**Writes to state:** `status="failed"`, `error`
**Behaviour:** terminal failure node; the runner persists `failed` + message.

---

## Graph / Flow Topology

```
START
  │
  ▼
plan ──(error)──► handle_error ──► END
  │
  ▼
generate_code ──(error)──► handle_error
  │
  ▼
execute_code
  │
  ▼ (after_execute router)
  ├─ exec_error or empty result, retries left ──► generate_code  (loop)
  ├─ error, retries exhausted ─────────────────► handle_error ──► END
  └─ result OK ────────────────────────────────► finalize ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| plan | `state["error"]` set | `handle_error` |
| plan | else | `generate_code` |
| generate_code | `state["error"]` set | `handle_error` |
| generate_code | else | `execute_code` |
| execute_code (`after_execute`) | `exec_error`/empty and `retry_count < max_retries` | `generate_code` (increment `retry_count`) |
| execute_code (`after_execute`) | `exec_error` and `retry_count >= max_retries` | `handle_error` |
| execute_code (`after_execute`) | result OK | `finalize` |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph state | plan, code, exec result, retries |
| **Across runs** | SQLite (`analyses`, `datasets`) | every question, code, result, timestamps (+ cost later); loaded datasets/schema |
| **Conversation** | `state["messages"]` threaded by the runner from prior `analyses` of the same dataset/session | prior turns so "now break that down by region" resolves contextually (Phase 2) |

**Context window management:** prompts carry only schema + bounded samples + a bounded number of recent turns; large computed results are truncated before being sent to `finalize`. This keeps tokens low (cost-conscious) and within limits regardless of file size.

---

## Human-in-the-Loop Checkpoints

None in the automatic path. On uncertainty the agent may surface a clarifying question as its answer (best-guess-with-flagged-assumptions is the default behaviour), but execution does not pause/block waiting for input — the user simply asks a follow-up. (Listed for completeness; no blocking checkpoint.)

---

## Error Handling & Recovery

**Node-level:** each node wraps its work in try/except; Gemini failures (after retry/backoff) set `state["error"]`. Sandbox failures are captured into `exec_error` (non-fatal — they drive the retry loop), not `error`.

**Graph-level (`handle_error` node):**
- Reads: `state["error"]` (or exhausted `exec_error`), `run_id`
- The runner updates the `analyses` row: status → `failed`, `error_message`, `completed_at`
- Logs the error with `run_id` context (structlog)
- Terminates the graph

**Resume / retry strategy:** within a run, the reflection loop regenerates code up to `max_retries`. Across runs there is no resume — a failed analysis is just re-asked by the user. (No checkpointer needed in Phase 1.)

**Partial failure:** if charting (Phase 2) fails but the numeric answer succeeded, the answer is still returned and the chart is omitted with a note — degrade, don't abort.

---

## Observability

| Signal | What | Where |
|--------|------|-------|
| **Trace** | One trace per analysis, one span per node | LangSmith if `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` set; else structured logs |
| **LLM calls** | Prompt payload (schema+samples only — auditable privacy boundary), output, tokens, latency, model | structlog (stdout) |
| **Code execution** | Generated code, success/error, duration | structlog |
| **Run outcome** | Status, total duration, error, (later) cost | SQLite (`analyses`) + structlog |

Observability is wired in Phase 1 (structured logging of the LLM payload is itself a success criterion proving the privacy boundary). LangSmith tracing is opt-in via env.

---

## Concurrency Model

- **Run isolation:** single user; analyses run one-at-a-time per request. Each invoke is `run_id`-scoped; no shared mutable graph state across requests.
- **Parallel nodes within a run:** none in Phase 1 (linear spine + retry loop). Multi-file (Phase 3) still loads files then runs one analysis — no node-level parallelism required.
- **Checkpointing:** none (no human-in-the-loop, runs are short). Loaded DataFrames are cached in-process keyed by `dataset_id` to avoid re-reading a ~100MB file per question.

---

## Graph Assembly (`src/graph/agent.py`)

```python
graph = StateGraph(AgentState)

graph.add_node("plan", plan)
graph.add_node("generate_code", generate_code)
graph.add_node("execute_code", execute_code)
graph.add_node("finalize", finalize)
graph.add_node("handle_error", handle_error)

graph.set_entry_point("plan")

graph.add_conditional_edges(
    "plan",
    lambda s: "handle_error" if s.get("error") else "generate_code",
    {"handle_error": "handle_error", "generate_code": "generate_code"},
)
graph.add_conditional_edges(
    "generate_code",
    lambda s: "handle_error" if s.get("error") else "execute_code",
    {"handle_error": "handle_error", "execute_code": "execute_code"},
)
graph.add_conditional_edges(
    "execute_code",
    after_execute,  # -> "generate_code" | "finalize" | "handle_error"
    {"generate_code": "generate_code", "finalize": "finalize", "handle_error": "handle_error"},
)

graph.add_edge("finalize", END)
graph.add_edge("handle_error", END)

agentic_ai = graph.compile()
```
