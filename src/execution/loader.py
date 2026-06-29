"""Dataset loading + the LLM-safe schema/sample extraction (privacy boundary).

The loader reads a CSV/Excel file fully into an in-memory pandas DataFrame and
derives the ONLY things ever shown to the LLM: the schema (column -> dtype) and
a small, JSON-serializable set of sample rows. Loaded DataFrames are cached
in-process by ``dataset_id`` so a ~100MB file is not re-read for every question.
"""

from __future__ import annotations

import math
import os
from typing import Any

import numpy as np
import pandas as pd

_DEFAULT_SAMPLE_ROWS = 5

# In-process cache of loaded DataFrames keyed by dataset_id. Avoids re-reading a
# large source file for every question in a single long-running process.
dataframe_cache: dict[str, pd.DataFrame] = {}


def _resolve_sample_rows(n: int | None) -> int:
    if n is not None:
        return int(n)
    raw = os.environ.get("AGENT_SAMPLE_ROWS", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            return _DEFAULT_SAMPLE_ROWS
    return _DEFAULT_SAMPLE_ROWS


def load_dataset(file_path: str, file_type: str) -> pd.DataFrame:
    """Load a CSV or Excel file fully into a pandas DataFrame.

    Args:
        file_path: absolute or relative path to the source file.
        file_type: ``"csv"`` or ``"xlsx"``/``"excel"`` (case-insensitive).

    Raises:
        ValueError: on an unsupported ``file_type``.
    """
    kind = (file_type or "").strip().lower()
    if kind in {"csv", "text/csv"}:
        return pd.read_csv(file_path)
    if kind in {"xlsx", "xls", "excel", "openpyxl"}:
        return pd.read_excel(file_path, engine="openpyxl")
    raise ValueError(
        f"unsupported file_type {file_type!r}; expected 'csv' or 'xlsx'"
    )


def extract_schema(df: pd.DataFrame) -> dict[str, str]:
    """Return ``{column_name: dtype_string}`` — safe to send to the LLM."""
    return {str(col): str(dtype) for col, dtype in df.dtypes.items()}


def _json_safe(value: Any) -> Any:
    """Cast a single cell value to a JSON-serializable Python scalar."""
    # Missing values (NaN, NaT, pd.NA) -> None.
    try:
        if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
            return None
    except (TypeError, ValueError):
        # pd.isna on array-like values raises; fall through to scalar handling.
        pass

    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        ts = pd.Timestamp(value)
        return None if pd.isna(ts) else ts.isoformat()
    if isinstance(value, (np.ndarray,)):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, float):
        return None if math.isnan(value) else value
    # int, str, bool, plain Python types pass through; coerce anything exotic.
    if isinstance(value, (int, str, bool)):
        return value
    return str(value)


def extract_samples(df: pd.DataFrame, n: int | None = None) -> list[dict]:
    """Return the first ``n`` rows as JSON-safe dicts (privacy-bounded).

    ``n`` defaults to ``AGENT_SAMPLE_ROWS`` (fallback 5). Length is
    ``min(n, len(df))``. Every value is cast to a JSON-serializable scalar so
    the result survives ``json.dumps`` without a custom encoder.
    """
    rows = _resolve_sample_rows(n)
    head = df.head(rows)
    samples: list[dict] = []
    for _, row in head.iterrows():
        samples.append({str(col): _json_safe(val) for col, val in row.items()})
    return samples


def get_or_load(dataset_id: str, file_path: str, file_type: str) -> pd.DataFrame:
    """Return the cached DataFrame for ``dataset_id`` or load + cache it.

    Keeps a single long-running process from re-reading a large source file for
    every question against the same dataset.
    """
    cached = dataframe_cache.get(dataset_id)
    if cached is not None:
        return cached
    frame = load_dataset(file_path, file_type)
    dataframe_cache[dataset_id] = frame
    return frame
