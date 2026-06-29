"""Pydantic request/response models for the datasets API.

Mirrors the `POST /datasets`, `GET /datasets` contract in `spec/api.md`.
Uploads arrive as multipart/form-data (handled in the router), so there is no
JSON request body model for creation — only the response shapes live here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DatasetResponse(BaseModel):
    """Response for `POST /datasets` — the freshly created dataset.

    The wire key is ``schema`` (per spec/api.md); the Python attribute is
    ``schema_`` to avoid clashing with ``BaseModel.schema``. Always serialize
    with ``model_dump(by_alias=True)`` so the spec key reaches the client.
    """

    model_config = ConfigDict(populate_by_name=True)

    dataset_id: str
    name: str
    file_type: str
    row_count: int
    schema_: dict[str, str] = Field(serialization_alias="schema", validation_alias="schema")
    samples: list[dict[str, Any]]
    profile: dict[str, Any] | None = None


class DatasetListItem(BaseModel):
    """One entry in the `GET /datasets` library list (Phase 3 view)."""

    dataset_id: str
    name: str
    file_type: str
    row_count: int
    created_at: str | None = None


class DatasetListResponse(BaseModel):
    """Response for `GET /datasets` — the dataset library (Phase 3 stub)."""

    datasets: list[DatasetListItem] = []
