"""Graph nodes for the data-analysis agent.

Pipeline: plan -> generate_code -> execute_code -> (retry loop) -> finalize,
with handle_error as the terminal failure node.

Privacy boundary (critical): the ONLY data ever placed in a Gemini prompt is the
schema (column -> dtype), bounded sample rows, the question, and the plan. The
full DataFrame is loaded locally in ``execute_code`` and NEVER serialized into a
prompt. Every LLM call logs its prompt payload via structlog so the boundary is
auditable.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from charts.spec import (
    build_vega_lite_spec,
    parse_chart_spec,
    result_to_chart_records,
)
from db.models import DatasetRow
from db.session import create_db_session
from execution.loader import extract_samples, extract_schema, get_or_load
from execution.sandbox import run_pandas
from graph.state import AgentState
from llm.client import LLMClient
from observability.events import get_logger

_log = get_logger("agent.graph")
_PROMPT_DIR = Path(__file__).parent.parent / "prompts"

# Bounded retry/backoff for transient Gemini errors (rate limit, 5xx, network).
_LLM_MAX_ATTEMPTS = 3
_LLM_BACKOFF_BASE_S = 1.5

# Cap the result text sent to finalize so a large table cannot blow the context.
_RESULT_MAX_CHARS = 4000


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def _call_gemini(system: str, prompt: str, *, node: str) -> str:
    """Call Gemini via LLMClient with bounded retry/backoff for transient errors.

    Logs the EXACT prompt payload (schema+samples+question+plan only — no raw
    rows) so the privacy boundary is auditable. Raises on persistent failure.
    """
    _log.info(
        "llm_call",
        node=node,
        system=system,
        prompt=prompt,  # auditable: contains only schema/samples/question/plan
        prompt_chars=len(prompt),
    )
    last_exc: Exception | None = None
    for attempt in range(1, _LLM_MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            out = LLMClient().call_model(prompt, system=system)
            _log.info(
                "llm_response",
                node=node,
                attempt=attempt,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                output_chars=len(out or ""),
            )
            return out
        except Exception as exc:  # noqa: BLE001 - retry transient, surface persistent
            last_exc = exc
            _log.warning(
                "llm_error",
                node=node,
                attempt=attempt,
                error=str(exc),
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
            if attempt < _LLM_MAX_ATTEMPTS:
                time.sleep(_LLM_BACKOFF_BASE_S * attempt)
    raise RuntimeError(f"Gemini call failed after {_LLM_MAX_ATTEMPTS} attempts: {last_exc}")


def _format_context(state: AgentState) -> str:
    """Schema + samples + question + prior turns — the LLM-visible payload."""
    schema = state.get("schema") or {}
    samples = state.get("samples") or []
    parts = [
        f"SCHEMA (column: dtype):\n{json.dumps(schema, indent=2, default=str)}",
        f"SAMPLE ROWS (first {len(samples)}):\n{json.dumps(samples, indent=2, default=str)}",
        f"QUESTION:\n{state.get('question', '')}",
    ]
    messages = state.get("messages") or []
    if messages:
        turns = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages[-6:]
        )
        parts.insert(2, f"PRIOR CONVERSATION:\n{turns}")
    return "\n\n".join(parts)


def _extract_code(text: str) -> str:
    """Strip a fenced ```python ... ``` block; fall back to the raw text."""
    if not text:
        return ""
    fenced = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def _is_empty_result(value: object) -> bool:
    """True when the computed result is unusable (None / empty / all-NaN)."""
    if value is None:
        return True
    try:
        import numpy as np
        import pandas as pd

        if isinstance(value, (pd.DataFrame, pd.Series)):
            if value.empty:
                return True
            return bool(pd.isna(value).all().all()) if isinstance(value, pd.DataFrame) else bool(pd.isna(value).all())
        if isinstance(value, (list, tuple, dict, set, str)):
            return len(value) == 0
        if isinstance(value, float) and np.isnan(value):
            return True
    except Exception:  # noqa: BLE001 - emptiness check must never raise
        return False
    return False


def _result_to_text(value: object) -> str:
    """Serialize a computed result to a bounded text form for finalize."""
    try:
        import pandas as pd

        if isinstance(value, (pd.DataFrame, pd.Series)):
            text = value.to_string()
        elif isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, indent=2, default=str)
        else:
            text = str(value)
    except Exception:  # noqa: BLE001
        text = str(value)
    if len(text) > _RESULT_MAX_CHARS:
        text = text[:_RESULT_MAX_CHARS] + "\n... [result truncated]"
    return text


def _describe_result_shape(value: object, records: list | None) -> str:
    """A privacy-safe, LLM-visible description of the computed result's SHAPE.

    Sends only column names / index name / row-count — never the raw values —
    so the chart prompt can pick fields without ever seeing the data.
    """
    try:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
            cols = [str(c) for c in value.columns]
            idx = value.index.name
            head = f"DataFrame with {len(value)} rows."
            if idx is not None:
                head += f" Index name: {idx!r} (becomes a column)."
            return f"{head} Columns: {cols}"
        if isinstance(value, pd.Series):
            cat = value.index.name or "category"
            val = value.name or "value"
            return (
                f"Series ({len(value)} entries) -> a breakdown with category "
                f"field {cat!r} and value field {val!r}."
            )
    except Exception:  # noqa: BLE001
        pass
    if records:
        keys = sorted({k for r in records for k in r})
        return f"Tabular result with {len(records)} rows. Fields: {keys}"
    return "A single scalar value (not a breakdown)."


def _parse_followups(text: str) -> list[str]:
    """Parse the followups LLM response into a bounded list of 2–3 strings."""
    if not text:
        return []
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()
    items: list[str] = []
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            items = [str(x).strip() for x in parsed if str(x).strip()]
    except (ValueError, TypeError):
        # Fallback: split lines, strip bullets/numbering.
        for line in stripped.splitlines():
            cleaned = re.sub(r"^\s*[-*\d.)\]]+\s*", "", line).strip().strip('"')
            if cleaned:
                items.append(cleaned)
    return items[:3]


def _result_to_json(value: object) -> str | None:
    """Best-effort JSON serialization of the result for persistence."""
    try:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
            payload = value.to_dict(orient="records")
        elif isinstance(value, pd.Series):
            payload = value.to_dict()
        else:
            payload = value
        return json.dumps(payload, default=str)
    except Exception:  # noqa: BLE001
        try:
            return json.dumps(str(value))
        except Exception:  # noqa: BLE001
            return None


# --- Nodes -------------------------------------------------------------------


def plan(state: AgentState) -> AgentState:
    """Gemini: short natural-language plan from schema+samples+question."""
    try:
        system = _load_prompt("plan.md")
        prompt = _format_context(state)
        out = _call_gemini(system, prompt, node="plan")
        return {**state, "plan": (out or "").strip()}
    except Exception as exc:  # noqa: BLE001 - persistent failure -> handle_error
        _log.error("plan_failed", run_id=state.get("run_id"), error=str(exc))
        return {**state, "error": f"plan failed: {exc}"}


def generate_code(state: AgentState) -> AgentState:
    """Gemini: a pandas snippet using `df` that assigns the answer to `result`.

    On retry, the prior code + sandbox error are included so the model
    self-corrects.
    """
    try:
        system = _load_prompt("generate_code.md")
        parts = [_format_context(state)]
        plan_text = state.get("plan")
        if plan_text:
            parts.append(f"PLAN:\n{plan_text}")
        prior_code = state.get("code")
        prior_error = state.get("exec_error")
        if prior_code and prior_error:
            parts.append(
                "YOUR PREVIOUS ATTEMPT FAILED. Fix it.\n"
                f"PREVIOUS CODE:\n```python\n{prior_code}\n```\n"
                f"EXECUTION ERROR:\n{prior_error}"
            )
        prompt = "\n\n".join(parts)
        out = _call_gemini(system, prompt, node="generate_code")
        code = _extract_code(out)
        if not code:
            return {**state, "error": "generate_code produced empty code"}
        # Clear the prior sandbox error now that we have a fresh attempt.
        return {**state, "code": code, "exec_error": None}
    except Exception as exc:  # noqa: BLE001
        _log.error("generate_code_failed", run_id=state.get("run_id"), error=str(exc))
        return {**state, "error": f"generate_code failed: {exc}"}


def execute_code(state: AgentState) -> AgentState:
    """Load the dataset DataFrame (cached) and run the snippet in the sandbox.

    Sandbox failures are captured into ``exec_error`` (non-fatal — they drive the
    retry loop), NOT raised.
    """
    dataset_id = state.get("dataset_id")
    code = state.get("code") or ""
    try:
        with create_db_session() as session:
            ds = session.get(DatasetRow, dataset_id)
            if ds is None:
                return {
                    **state,
                    "exec_result": None,
                    "exec_stdout": "",
                    "exec_error": None,
                    "error": f"dataset not found: {dataset_id}",
                }
            file_path, file_type = ds.file_path, ds.file_type
        df = get_or_load(dataset_id, file_path, file_type)
    except Exception as exc:  # noqa: BLE001 - loading is fatal, not a code retry
        _log.error("execute_load_failed", run_id=state.get("run_id"), error=str(exc))
        return {**state, "error": f"failed to load dataset: {exc}"}

    timeout = _exec_timeout()
    outcome = run_pandas(code, {"df": df}, timeout_s=timeout)
    _log.info(
        "code_execution",
        run_id=state.get("run_id"),
        retry_count=state.get("retry_count", 0),
        ok=outcome.get("error") is None,
        error=outcome.get("error"),
        code_chars=len(code),
    )
    return {
        **state,
        "exec_result": outcome.get("result"),
        "exec_stdout": outcome.get("stdout"),
        "exec_error": outcome.get("error"),
    }


def finalize(state: AgentState) -> AgentState:
    """Gemini: plain-language answer from question+plan+computed result."""
    try:
        system = _load_prompt("finalize.md")
        result_text = _result_to_text(state.get("exec_result"))
        prompt = (
            f"QUESTION:\n{state.get('question', '')}\n\n"
            f"PLAN:\n{state.get('plan', '')}\n\n"
            f"COMPUTED RESULT:\n{result_text}"
        )
        out = _call_gemini(system, prompt, node="finalize")
        return {**state, "answer": (out or "").strip(), "status": "completed"}
    except Exception as exc:  # noqa: BLE001
        _log.error("finalize_failed", run_id=state.get("run_id"), error=str(exc))
        return {**state, "error": f"finalize failed: {exc}"}


def render_chart(state: AgentState) -> AgentState:
    """Gemini: emit a Vega-Lite spec skeleton; embed the LOCALLY-computed data.

    The LLM sees only the question, plan, schema, and the SHAPE of the result —
    never raw values. It returns a mark+encoding skeleton (or NONE). This node
    embeds the real, locally-computed result as ``data.values`` so the chart
    shows true numbers. Charting is best-effort: any failure degrades to no
    chart (the numeric answer still stands) — it never aborts the run.
    """
    try:
        records = result_to_chart_records(state.get("exec_result"))
        if not records:
            _log.info("chart_skipped", run_id=state.get("run_id"), reason="not_chartable")
            return {**state, "chart_spec": None}

        system = _load_prompt("chart.md")
        schema = state.get("schema") or {}
        shape = _describe_result_shape(state.get("exec_result"), records)
        prompt = (
            f"QUESTION:\n{state.get('question', '')}\n\n"
            f"PLAN:\n{state.get('plan', '')}\n\n"
            f"SCHEMA (column: dtype):\n{json.dumps(schema, indent=2, default=str)}\n\n"
            f"RESULT SHAPE (no values shown):\n{shape}"
        )
        out = _call_gemini(system, prompt, node="render_chart")
        skeleton = parse_chart_spec(out)
        spec = build_vega_lite_spec(skeleton, records)
        _log.info(
            "chart_built",
            run_id=state.get("run_id"),
            charted=spec is not None,
            rows=len(records),
        )
        return {**state, "chart_spec": spec}
    except Exception as exc:  # noqa: BLE001 - degrade, never abort
        _log.warning("render_chart_failed", run_id=state.get("run_id"), error=str(exc))
        return {**state, "chart_spec": None}


def suggest_followups(state: AgentState) -> AgentState:
    """Gemini: 2–3 short follow-up questions building on the answer.

    Best-effort: a failure yields an empty list rather than aborting the run.
    """
    try:
        system = _load_prompt("followups.md")
        schema = state.get("schema") or {}
        prompt = (
            f"QUESTION:\n{state.get('question', '')}\n\n"
            f"PLAN:\n{state.get('plan', '')}\n\n"
            f"SCHEMA (column: dtype):\n{json.dumps(schema, indent=2, default=str)}\n\n"
            f"ANSWER:\n{state.get('answer', '')}"
        )
        out = _call_gemini(system, prompt, node="suggest_followups")
        followups = _parse_followups(out)
        _log.info("followups_built", run_id=state.get("run_id"), count=len(followups))
        return {**state, "followups": followups or None}
    except Exception as exc:  # noqa: BLE001 - degrade, never abort
        _log.warning("suggest_followups_failed", run_id=state.get("run_id"), error=str(exc))
        return {**state, "followups": None}


def handle_error(state: AgentState) -> AgentState:
    """Terminal failure node — records status=failed, keeps error + last code."""
    error = state.get("error") or state.get("exec_error") or "unknown error"
    _log.error(
        "run_failed",
        run_id=state.get("run_id"),
        error=error,
        retry_count=state.get("retry_count", 0),
    )
    return {**state, "status": "failed", "error": error}


# --- helpers -----------------------------------------------------------------


def _exec_timeout() -> int | None:
    raw = os.environ.get("AGENT_EXEC_TIMEOUT_S", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            return None
    return None
