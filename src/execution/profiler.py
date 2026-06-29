"""Auto-profiling of a loaded dataset (Phase 2 — ``auto_profile_dataset``).

On upload the agent profiles the full DataFrame locally and persists a compact,
JSON-safe profile on the dataset row. The profile is derived ENTIRELY locally
(it is computed over every row, not a sample) and is itself LLM-safe metadata in
the same spirit as schema/samples: per-column type, non-null count, missing
count, numeric min/max/mean, and categorical distinct-count / top values. Raw
rows are never serialized — only aggregates and a bounded set of top category
labels (which are column values, kept local in SQLite and shown only in the
profile panel, never sent to the LLM by the profiler).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

# How many top category values to surface for a categorical/object column.
_TOP_VALUES = 5


def _json_number(value: Any) -> float | int | None:
    """Cast a numpy/pandas scalar to a JSON-safe Python number (or None)."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, (int,)):
        return int(value)
    return None


def _scalar(value: Any) -> Any:
    """Cast a single category value to a JSON-safe scalar for top-values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
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
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def profile_dataset(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Profile every column of ``df`` and return a JSON-safe per-column dict.

    Returns ``{column: {...stats...}}`` where every column has:

    - ``type``: the pandas dtype string.
    - ``count``: number of non-null values.
    - ``missing``: number of null/NaN values.

    Numeric columns additionally carry ``min``/``max``/``mean`` (None if no
    numeric data). Non-numeric (categorical/object/bool/datetime) columns carry
    ``distinct`` (distinct non-null count) and ``top`` (a bounded list of
    ``{"value", "count"}`` for the most frequent values).

    The whole DataFrame is scanned (not sampled) so missing-value counts and
    ranges are exact and match a hand-computed pandas profile.
    """
    n = len(df)
    profile: dict[str, dict[str, Any]] = {}

    for col in df.columns:
        series = df[col]
        missing = int(series.isna().sum())
        count = int(n - missing)
        col_profile: dict[str, Any] = {
            "type": str(series.dtype),
            "count": count,
            "missing": missing,
        }

        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            col_profile["min"] = _json_number(series.min())
            col_profile["max"] = _json_number(series.max())
            col_profile["mean"] = _json_number(series.mean())
        else:
            non_null = series.dropna()
            col_profile["distinct"] = int(non_null.nunique())
            top_counts = non_null.value_counts().head(_TOP_VALUES)
            col_profile["top"] = [
                {"value": _scalar(value), "count": int(freq)}
                for value, freq in top_counts.items()
            ]

        profile[str(col)] = col_profile

    return profile
