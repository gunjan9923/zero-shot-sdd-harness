"""Conditional routing for the data-analysis graph.

The plan/generate_code routers are inline lambdas in ``agent.py`` (per
spec/agent.md's assembly). ``after_execute`` is the reflection/retry decision and
lives here because it mutates ``retry_count`` when it routes back.
"""

from graph.nodes import _is_empty_result
from graph.state import AgentState


def after_execute(state: AgentState) -> str:
    """Route after ``execute_code``.

    - Fatal load error (state["error"] set) -> handle_error.
    - exec_error OR empty/None/all-NaN result, with retries left ->
      generate_code (increment retry_count, mutated on state in place).
    - exec_error with retries exhausted -> handle_error.
    - result OK -> finalize.
    """
    if state.get("error"):
        return "handle_error"

    exec_error = state.get("exec_error")
    empty = _is_empty_result(state.get("exec_result"))
    needs_retry = bool(exec_error) or empty

    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if needs_retry:
        if retry_count < max_retries:
            # Mutate in place so the loop counter survives the next node.
            state["retry_count"] = retry_count + 1
            return "generate_code"
        # Retries exhausted. Surface a useful error for handle_error.
        if not state.get("exec_error"):
            state["exec_error"] = "computed result was empty/None/all-NaN after retries"
        state["error"] = state.get("error") or state["exec_error"]
        return "handle_error"

    return "finalize"
