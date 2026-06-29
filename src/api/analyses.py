"""Analyses router — ask a question about a dataset and fetch the result.

`POST /analyses` validates the request, runs the agent end-to-end via
``run_agent`` (real LLM), then returns the persisted AnalysisRow shaped per
spec/api.md. A *failed* analysis still surfaces the last code it tried, via a
422 whose ``detail`` carries the full analysis fields (see FAILED_DETAIL below).
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import api_error, ok
from db.models import AnalysisRow, DatasetRow
from db.session import get_session
from domain.analysis import AnalysisRequest, AnalysisResponse
from graph.runner import run_agent
from observability.events import get_logger

router = APIRouter()
_log = get_logger("api.analyses")


def _parse_result(result_json: str | None) -> Any | None:
    if not result_json:
        return None
    try:
        return json.loads(result_json)
    except (ValueError, TypeError):
        # Stored as a non-JSON string (legacy/raw) — hand it back as-is.
        return result_json


def _parse_json(value: str | None) -> Any | None:
    """Parse a stored JSON column, tolerating null/legacy non-JSON text."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def _build_history(session: Session, dataset_id: str) -> list[dict[str, str]]:
    """Reconstruct conversation history from prior completed analyses.

    The API request shape is fixed (no client-sent transcript), so follow-up
    context is derived server-side from earlier completed Q&A on the SAME
    dataset, oldest-first. Only the question + answer text is threaded — never
    raw data — preserving the schema+samples-only privacy boundary.
    """
    rows = session.execute(
        select(AnalysisRow)
        .where(AnalysisRow.dataset_id == dataset_id)
        .where(AnalysisRow.status == "completed")
        .order_by(AnalysisRow.created_at.asc())
    ).scalars().all()
    history: list[dict[str, str]] = []
    for r in rows:
        if r.question:
            history.append({"role": "user", "content": r.question})
        if r.answer:
            history.append({"role": "assistant", "content": r.answer})
    return history


def _to_response(row: AnalysisRow) -> AnalysisResponse:
    """Build the wire response from a persisted AnalysisRow."""
    return AnalysisResponse(
        analysis_id=row.id,
        status=row.status,
        answer=row.answer,
        plan=row.plan,
        code=row.code,
        result=_parse_result(row.result_json),
        retry_count=int(row.retry_count or 0),
        chart_spec=_parse_json(row.chart_spec_json),  # Phase 2
        followups=_parse_json(row.followups_json),     # Phase 2
        tokens=None,            # Phase 3
        estimated_cost_usd=None,  # Phase 3
        error=row.error_message,
    )


@router.post("/analyses")
def create_analysis(
    req: AnalysisRequest,
    session: Session = Depends(get_session),
) -> Any:
    started = time.monotonic()
    question = (req.question or "").strip()
    if not question:
        raise api_error("BAD_REQUEST", "Missing question", 400)

    ds = session.get(DatasetRow, req.dataset_id)
    if ds is None:
        raise api_error("BAD_REQUEST", f"Unknown dataset_id: {req.dataset_id}", 400)

    # Thread prior Q&A on this dataset so follow-ups ("now by region") resolve
    # in context. Built before the run so the current question is excluded.
    history = _build_history(session, req.dataset_id)

    _log.info(
        "analysis_start",
        dataset_id=req.dataset_id,
        question_len=len(question),
        history_turns=len(history),
    )
    try:
        analysis_id = run_agent(req.dataset_id, question, messages=history)
    except ValueError as exc:
        # Defensive: run_agent raises ValueError for an unknown dataset; we
        # already validated above, so treat any other ValueError as a 400.
        raise api_error("BAD_REQUEST", str(exc), 400)
    except Exception as exc:  # unexpected internal failure — clean 500, no trace
        _log.error("analysis_internal_error", dataset_id=req.dataset_id, error=str(exc))
        raise api_error("INTERNAL_ERROR", "Internal error while running the analysis", 500)

    row = session.get(AnalysisRow, analysis_id)
    if row is None:
        _log.error("analysis_missing_after_run", analysis_id=analysis_id)
        raise api_error("INTERNAL_ERROR", "Analysis not found after creation", 500)

    body = _to_response(row)
    latency_ms = round((time.monotonic() - started) * 1000, 1)
    _log.info(
        "analysis_done",
        analysis_id=analysis_id,
        status=row.status,
        retry_count=body.retry_count,
        latency_ms=latency_ms,
    )

    if row.status == "failed":
        # FAILED_DETAIL contract: a failed analysis returns HTTP 422, but the
        # `detail` object carries BOTH the human message AND the full analysis
        # fields (analysis_id, code, answer, plan, result, ...). The frontend
        # reads `detail.message` for the error banner and `detail.code` to show
        # the last pandas code the agent attempted (spec/ui.md requirement).
        # The error-classification string lives under `error_code` so it never
        # shadows `code` (which is the agent's last pandas code).
        detail = {
            "error_code": "ANALYSIS_FAILED",
            "message": row.error_message or "The agent could not produce a valid answer.",
            **body.model_dump(),  # includes analysis_id, code, answer, plan, result, ...
        }
        return JSONResponse(status_code=422, content={"detail": detail})

    return ok(body.model_dump())


@router.get("/analyses/{analysis_id}")
def get_analysis(
    analysis_id: str,
    session: Session = Depends(get_session),
) -> dict:
    row = session.get(AnalysisRow, analysis_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Analysis {analysis_id} not found", 404)
    return ok(_to_response(row).model_dump())
