"""Pydantic request/response models for the analyses API.

Mirrors the `POST /analyses`, `GET /analyses/{id}` contract in `spec/api.md`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AnalysisRequest(BaseModel):
    """Request body for `POST /analyses`."""

    dataset_id: str
    question: str
    # Optional Phase 3 multi-file selection; defaults to [dataset_id] downstream.
    dataset_ids: list[str] | None = None


class AnalysisResponse(BaseModel):
    """Response shape shared by `POST /analyses` and `GET /analyses/{id}`."""

    analysis_id: str
    status: str
    answer: str | None = None
    plan: str | None = None
    code: str | None = None
    result: Any | None = None
    retry_count: int = 0
    chart_spec: dict[str, Any] | None = None   # Phase 2
    followups: list[str] | None = None         # Phase 2
    tokens: int | None = None                  # Phase 3
    estimated_cost_usd: float | None = None    # Phase 3
    error: str | None = None
