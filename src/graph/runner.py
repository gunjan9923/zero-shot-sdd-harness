"""Entry point that drives one analysis run end-to-end.

Creates the ``AnalysisRow`` (status pending), loads the dataset's LLM-safe
schema + samples (full data stays local), invokes the compiled graph, and
persists plan/code/result/answer/status/retry_count/completed_at back to the row.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from db.models import AnalysisRow, DatasetRow
from db.session import create_db_session, init_db
from execution.loader import extract_samples, extract_schema, get_or_load
from graph.agent import agentic_ai
from graph.nodes import _result_to_json
from graph.state import AgentState
from observability.events import get_logger
from observability.usage import estimate_cost_usd, get_usage, reset_usage

_log = get_logger("agent.runner")


def _max_retries() -> int:
    raw = os.environ.get("AGENT_MAX_RETRIES", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            return 2
    return 2


# Graph node name -> user-facing live-progress step label (Phase 3 streaming).
STEP_LABELS: dict[str, str] = {
    "plan": "planning",
    "generate_code": "generating_code",
    "execute_code": "running_code",
    "finalize": "finalizing",
    "render_chart": "building_chart",
    "suggest_followups": "suggesting_followups",
    "handle_error": "error",
}


def _prepare_run(
    dataset_id: str,
    question: str,
    messages: list | None,
    dataset_ids: list[str] | None,
) -> tuple[str, AgentState]:
    """Create the pending AnalysisRow + assemble the initial graph state.

    Returns ``(run_id, initial_state)``. Raises ``ValueError`` if any selected
    dataset is missing.
    """
    init_db()

    # Resolve the ordered, de-duplicated set of datasets (primary first).
    ids: list[str] = [dataset_id]
    for did in dataset_ids or []:
        if did not in ids:
            ids.append(did)

    files: list[dict] = []
    with create_db_session() as session:
        for i, did in enumerate(ids):
            ds = session.get(DatasetRow, did)
            if ds is None:
                raise ValueError(f"dataset not found: {did}")
            schema = json.loads(ds.schema_json) if ds.schema_json else None
            samples = json.loads(ds.samples_json) if ds.samples_json else None
            if schema is None or samples is None:
                df = get_or_load(did, ds.file_path, ds.file_type)
                schema = schema or extract_schema(df)
                samples = samples or extract_samples(df)
            # Single file keeps the proven "df" variable; multi-file uses df1..N.
            var = "df" if len(ids) == 1 else f"df{i + 1}"
            files.append(
                {
                    "dataset_id": did,
                    "name": ds.name,
                    "var": var,
                    "file_path": ds.file_path,
                    "file_type": ds.file_type,
                    "schema": schema,
                    "samples": samples,
                }
            )

        analysis = AnalysisRow(
            dataset_id=dataset_id,
            dataset_ids_json=json.dumps(ids),
            question=question,
            status="pending",
        )
        session.add(analysis)
        session.flush()
        run_id = analysis.id

    primary = files[0]
    initial: AgentState = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "dataset_ids": ids,
        "question": question,
        "messages": messages or [],
        "schema": primary["schema"],
        "samples": primary["samples"],
        "files": files,
        "retry_count": 0,
        "max_retries": _max_retries(),
        "error": None,
    }
    return run_id, initial


def _persist_outcome(run_id: str, final: AgentState, usage: dict[str, int], cost: float) -> str:
    """Write the graph's final state back onto the AnalysisRow. Returns status."""
    status = final.get("status") or ("failed" if final.get("error") else "completed")
    with create_db_session() as session:
        analysis = session.get(AnalysisRow, run_id)
        analysis.plan = final.get("plan")
        analysis.code = final.get("code")
        analysis.result_json = _result_to_json(final.get("exec_result"))
        analysis.answer = final.get("answer")
        chart_spec = final.get("chart_spec")
        analysis.chart_spec_json = json.dumps(chart_spec) if chart_spec else None
        followups = final.get("followups")
        analysis.followups_json = json.dumps(followups) if followups else None
        analysis.status = status
        analysis.error_message = final.get("error") if status == "failed" else None
        analysis.retry_count = int(final.get("retry_count", 0) or 0)
        analysis.prompt_tokens = usage["prompt_tokens"]
        analysis.completion_tokens = usage["completion_tokens"]
        analysis.estimated_cost_usd = cost
        analysis.completed_at = datetime.now(timezone.utc)
    _log.info(
        "run_end",
        run_id=run_id,
        status=status,
        retry_count=final.get("retry_count", 0),
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        estimated_cost_usd=cost,
    )
    return status


def run_agent(
    dataset_id: str,
    question: str,
    *,
    messages: list | None = None,
    dataset_ids: list[str] | None = None,
) -> str:
    """Run one analysis (blocking) and return the persisted ``AnalysisRow.id``."""
    run_id, initial = _prepare_run(dataset_id, question, messages, dataset_ids)
    _log.info("run_start", run_id=run_id, dataset_id=dataset_id)
    reset_usage()
    final = agentic_ai.invoke(initial)
    usage = get_usage()
    cost = estimate_cost_usd(usage["prompt_tokens"], usage["completion_tokens"])
    _persist_outcome(run_id, final, usage, cost)
    return run_id


def run_agent_stream(
    dataset_id: str,
    question: str,
    *,
    messages: list | None = None,
    dataset_ids: list[str] | None = None,
):
    """Run one analysis, yielding live progress events as the graph advances.

    Yields dicts: ``{"step": <label>}`` per node, then a terminal
    ``{"step": "done", "analysis_id", "status"}``. Persists the outcome before
    the final event so a client can immediately fetch the full analysis.
    """
    run_id, initial = _prepare_run(dataset_id, question, messages, dataset_ids)
    _log.info("run_start_stream", run_id=run_id, dataset_id=dataset_id)
    reset_usage()

    # Reconstruct the final state from per-node updates while emitting steps.
    final: dict = dict(initial)
    for chunk in agentic_ai.stream(initial, stream_mode="updates"):
        for node_name, update in chunk.items():
            if isinstance(update, dict):
                final.update(update)
            yield {"step": STEP_LABELS.get(node_name, node_name)}

    usage = get_usage()
    cost = estimate_cost_usd(usage["prompt_tokens"], usage["completion_tokens"])
    status = _persist_outcome(run_id, final, usage, cost)
    yield {"step": "done", "analysis_id": run_id, "status": status}
