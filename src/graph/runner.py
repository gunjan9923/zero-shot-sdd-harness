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

_log = get_logger("agent.runner")


def _max_retries() -> int:
    raw = os.environ.get("AGENT_MAX_RETRIES", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            return 2
    return 2


def run_agent(
    dataset_id: str,
    question: str,
    *,
    messages: list | None = None,
) -> str:
    """Run one analysis and return the persisted ``AnalysisRow.id``.

    Args:
        dataset_id: the dataset to analyse (must reference an existing row).
        question: the user's natural-language question.
        messages: optional prior chat turns for follow-up context.

    Returns:
        The analysis id. Inspect the persisted ``AnalysisRow`` for the full
        result (plan, code, result_json, answer, status, error_message).
    """
    init_db()

    # --- Create the pending analysis + read the dataset for schema/samples ----
    with create_db_session() as session:
        ds = session.get(DatasetRow, dataset_id)
        if ds is None:
            raise ValueError(f"dataset not found: {dataset_id}")
        file_path, file_type = ds.file_path, ds.file_type
        schema = json.loads(ds.schema_json) if ds.schema_json else None
        samples = json.loads(ds.samples_json) if ds.samples_json else None

        analysis = AnalysisRow(
            dataset_id=dataset_id,
            dataset_ids_json=json.dumps([dataset_id]),
            question=question,
            status="pending",
        )
        session.add(analysis)
        session.flush()
        run_id = analysis.id

    # Prefer the stored LLM-safe schema/samples; derive from the cached
    # DataFrame as a fallback if the row lacked them.
    if schema is None or samples is None:
        df = get_or_load(dataset_id, file_path, file_type)
        schema = schema or extract_schema(df)
        samples = samples or extract_samples(df)

    initial: AgentState = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "dataset_ids": [dataset_id],
        "question": question,
        "messages": messages or [],
        "schema": schema,
        "samples": samples,
        "retry_count": 0,
        "max_retries": _max_retries(),
        "error": None,
    }

    _log.info("run_start", run_id=run_id, dataset_id=dataset_id)
    final = agentic_ai.invoke(initial)

    status = final.get("status") or ("failed" if final.get("error") else "completed")

    # --- Persist the outcome --------------------------------------------------
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
        analysis.completed_at = datetime.now(timezone.utc)

    _log.info("run_end", run_id=run_id, status=status, retry_count=final.get("retry_count", 0))
    return run_id
