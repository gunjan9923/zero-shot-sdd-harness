from typing import TypedDict


class AgentState(TypedDict, total=False):
    """State threaded through the data-analysis agent graph.

    Privacy boundary: only ``schema`` + ``samples`` (plus the question/plan) are
    ever placed in an LLM prompt. The full DataFrame is loaded locally in
    ``execute_code`` and never serialized into a prompt.
    """

    # Identity
    run_id: str                       # analysis id, set at initialisation
    dataset_id: str                   # the primary dataset being analysed
    dataset_ids: list[str]            # multi-file (Phase 3); single-element in Phase 1

    # Input
    question: str                     # the user's natural-language question
    messages: list                    # prior chat turns [{role, content}] for follow-up context

    # Schema/sample context (privacy boundary — what the LLM may see)
    schema: dict                      # {column: dtype, ...}
    samples: list                     # bounded sample rows (default 5)

    # Pipeline data (populated progressively by nodes)
    plan: str                         # natural-language approach (plan node)
    code: str                         # generated pandas snippet (generate_code node)
    exec_result: object | None        # value of `result` from the sandbox
    exec_stdout: str | None           # captured stdout
    exec_error: str | None            # sandbox exception/timeout text (drives retry)
    retry_count: int                  # incremented each regenerate; bounded by max_retries
    max_retries: int                  # default 2 (env AGENT_MAX_RETRIES)

    # Output
    answer: str                       # final plain-language answer (finalize node)
    status: str                       # "completed" | "failed"

    # Phase 2 — insight layer
    chart_spec: dict | None           # Vega-Lite spec (data embedded) or None (render_chart)
    followups: list | None            # 2–3 suggested follow-up questions (suggest_followups)

    # Control
    error: str | None                 # fatal error → handle_error
