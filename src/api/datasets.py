"""Datasets router — upload a CSV/Excel file and list the library.

`POST /datasets` stores the uploaded bytes under ``./data/uploads/`` (never in
the DB — only the path + extracted, LLM-safe metadata are persisted), loads the
file once to derive schema + sample rows + row_count, and creates a DatasetRow.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import api_error, ok
from db.models import DatasetRow
from db.session import get_session
from domain.dataset import (
    DatasetListItem,
    DatasetListResponse,
    DatasetResponse,
)
from execution.loader import (
    extract_samples,
    extract_schema,
    get_or_load,
    load_dataset,
)
from execution.profiler import profile_dataset
from observability.events import get_logger

router = APIRouter()
_log = get_logger("api.datasets")

UPLOAD_DIR = Path("./data/uploads")

# Extension -> internal file_type label understood by the loader.
_EXT_TO_TYPE = {".csv": "csv", ".xlsx": "xlsx"}


def _resolve_file_type(filename: str) -> str | None:
    ext = Path(filename or "").suffix.lower()
    return _EXT_TO_TYPE.get(ext)


@router.post("/datasets")
def create_dataset(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    started = time.monotonic()
    original_name = file.filename or "upload"
    file_type = _resolve_file_type(original_name)
    if file_type is None:
        _log.info("dataset_rejected", reason="bad_file_type", name=original_name)
        raise api_error("BAD_FILE", "Unsupported file type", 400)

    raw = file.file.read()
    if not raw:
        _log.info("dataset_rejected", reason="empty_file", name=original_name)
        raise api_error("BAD_FILE", "Uploaded file is empty", 400)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = os.path.basename(original_name)
    stored_path = UPLOAD_DIR / f"{uuid.uuid4()}__{safe_name}"
    try:
        stored_path.write_bytes(raw)
    except OSError as exc:
        _log.error("dataset_store_failed", name=original_name, error=str(exc))
        raise api_error("STORAGE_FAILED", "Could not store the uploaded file", 500)

    try:
        df = load_dataset(str(stored_path), file_type)
    except Exception as exc:  # parse errors from pandas/openpyxl
        _log.info("dataset_parse_failed", name=original_name, error=str(exc))
        # Drop the unusable file so we don't accumulate garbage on disk.
        stored_path.unlink(missing_ok=True)
        raise api_error("BAD_FILE", "Could not parse this CSV/Excel", 400)

    schema = extract_schema(df)
    samples = extract_samples(df)
    row_count = int(len(df))
    size_bytes = int(stored_path.stat().st_size)

    # Auto-profile the full DataFrame locally (Phase 2). Best-effort: a profiling
    # failure must never fail the upload — the dataset is still usable.
    try:
        profile = profile_dataset(df)
    except Exception as exc:  # noqa: BLE001
        _log.info("dataset_profile_failed", name=original_name, error=str(exc))
        profile = None

    ds = DatasetRow(
        name=original_name,
        file_path=str(stored_path),
        file_type=file_type,
        row_count=row_count,
        schema_json=json.dumps(schema),
        samples_json=json.dumps(samples),
        profile_json=json.dumps(profile) if profile is not None else None,
        size_bytes=size_bytes,
    )
    session.add(ds)
    session.flush()  # populate ds.id within this request's transaction
    dataset_id = ds.id

    # Prime the in-process loader cache so the first question is fast.
    try:
        get_or_load(dataset_id, str(stored_path), file_type)
    except Exception as exc:  # caching is best-effort; never fail the upload
        _log.info("dataset_cache_prime_failed", dataset_id=dataset_id, error=str(exc))

    _log.info(
        "dataset_created",
        dataset_id=dataset_id,
        name=original_name,
        file_type=file_type,
        row_count=row_count,
        size_bytes=size_bytes,
        latency_ms=round((time.monotonic() - started) * 1000, 1),
    )

    body = DatasetResponse(
        dataset_id=dataset_id,
        name=original_name,
        file_type=file_type,
        row_count=row_count,
        schema_=schema,
        samples=samples,
        profile=profile,
    )
    return ok(body.model_dump(by_alias=True))


@router.get("/datasets/{dataset_id}/profile")
def get_dataset_profile(
    dataset_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Fetch the auto-profile for a dataset (Phase 2)."""
    ds = session.get(DatasetRow, dataset_id)
    if ds is None:
        raise api_error("NOT_FOUND", f"Dataset {dataset_id} not found", 404)
    profile = json.loads(ds.profile_json) if ds.profile_json else None
    return ok({"profile": profile})


@router.get("/datasets")
def list_datasets(session: Session = Depends(get_session)) -> dict:
    """List persisted datasets for the library sidebar (Phase 3 surface).

    Returns a real (possibly empty) list now so the UI never 404s; the full
    library view is a labelled Phase 3 stub on the frontend.
    """
    rows = session.execute(
        select(DatasetRow).order_by(DatasetRow.created_at.desc())
    ).scalars().all()
    items = [
        DatasetListItem(
            dataset_id=r.id,
            name=r.name,
            file_type=r.file_type,
            row_count=r.row_count,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return ok(DatasetListResponse(datasets=items).model_dump())
