"""Vega-Lite chart-spec assembly (Phase 2 — ``render_chart``).

Privacy + correctness model: the LLM never sees raw data. It is shown only the
schema, samples, the question, the plan, and the SHAPE of the computed result,
and it emits a Vega-Lite spec *skeleton* (mark + encoding) with NO inline data.
The actual chart data is the result the agent computed locally in the sandbox;
this module embeds that locally-computed data into the spec's ``data.values``.
So the numbers a user sees in the chart are the real, locally-computed numbers,
not anything the LLM produced.

A chart is only produced when the question warrants one (the LLM may decline by
returning ``null``/an empty object) AND the computed result is chartable (a
tabular/series breakdown — a single scalar is not charted).
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

# Cap embedded rows so a huge breakdown cannot bloat the spec / payload.
_MAX_CHART_ROWS = 200


def result_to_chart_records(value: object) -> list[dict[str, Any]] | None:
    """Convert a computed result into a list of JSON-safe records for a chart.

    - DataFrame -> ``to_dict(orient="records")`` (index dropped unless named).
    - Series   -> ``[{<index_name|"category">: idx, <name|"value">: val}, ...]``.
    - Anything scalar / non-tabular -> ``None`` (not chartable).

    Returns ``None`` when there is nothing chartable (a single number, empty
    result, or an unconvertible value).
    """
    try:
        if isinstance(value, pd.DataFrame):
            if value.empty:
                return None
            frame = value
            # Promote a meaningful (named) index to a column so it can be encoded.
            if frame.index.name is not None or not isinstance(
                frame.index, pd.RangeIndex
            ):
                frame = frame.reset_index()
            records = frame.head(_MAX_CHART_ROWS).to_dict(orient="records")
            return [_json_safe_record(r) for r in records] or None

        if isinstance(value, pd.Series):
            if value.empty:
                return None
            cat_key = value.index.name or "category"
            val_key = value.name or "value"
            if cat_key == val_key:
                val_key = "value"
            records = [
                {cat_key: _json_safe(idx), val_key: _json_safe(val)}
                for idx, val in value.head(_MAX_CHART_ROWS).items()
            ]
            return records or None
    except Exception:  # noqa: BLE001 - charting is best-effort; degrade to None
        return None

    return None


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        if not isinstance(value, (list, dict)) and pd.isna(value):
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
    if isinstance(value, np.datetime64):
        ts = pd.Timestamp(value)
        return None if pd.isna(ts) else ts.isoformat()
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _json_safe_record(record: dict[Any, Any]) -> dict[str, Any]:
    return {str(k): _json_safe(v) for k, v in record.items()}


def parse_chart_spec(text: str) -> dict[str, Any] | None:
    """Parse the LLM's chart response into a spec skeleton, or ``None``.

    The model may return a fenced JSON block, raw JSON, or an explicit decline
    (``null``, ``{}``, or the literal text ``NONE``/``NO_CHART``). Returns the
    parsed dict (without any data), or ``None`` to mean "no chart".
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.upper() in {"NONE", "NO_CHART", "NULL"}:
        return None

    fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()

    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return None

    if not isinstance(parsed, dict) or not parsed:
        return None
    # A bare {"chart": null} style decline.
    if parsed.get("chart") is None and "mark" not in parsed and "encoding" not in parsed:
        return None
    return parsed


def build_vega_lite_spec(
    skeleton: dict[str, Any] | None,
    records: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Assemble a complete, valid Vega-Lite spec from a skeleton + local data.

    - Returns ``None`` if there is no skeleton or no chartable records.
    - Strips any LLM-supplied ``data`` (the model must never inject data) and
      replaces it with the locally-computed ``records`` as ``data.values``.
    - Ensures ``$schema``, ``mark``, and ``encoding`` are present; if the
      skeleton lacks an encoding, auto-picks one from the record columns.
    """
    if not skeleton or not records:
        return None

    spec: dict[str, Any] = {
        k: v for k, v in skeleton.items() if k not in {"data", "$schema"}
    }
    spec["$schema"] = "https://vega.github.io/schema/vega-lite/v5.json"

    mark = spec.get("mark")
    if not mark:
        spec["mark"] = _auto_mark(records)
    encoding = spec.get("encoding")
    if not isinstance(encoding, dict) or not encoding:
        spec["encoding"] = _auto_encoding(records)

    # The data is ALWAYS the locally-computed result — never the LLM's.
    spec["data"] = {"values": records}
    return spec


def _columns(records: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for rec in records:
        for k in rec:
            if k not in keys:
                keys.append(k)
    return keys


def _is_numeric_column(records: list[dict[str, Any]], col: str) -> bool:
    seen = False
    for rec in records:
        v = rec.get(col)
        if v is None:
            continue
        seen = True
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
    return seen


def _auto_mark(records: list[dict[str, Any]]) -> str:
    cols = _columns(records)
    numeric = [c for c in cols if _is_numeric_column(records, c)]
    # Two-or-more numeric columns -> scatter; otherwise a bar of category->value.
    if len(numeric) >= 2 and len(cols) == len(numeric):
        return "point"
    return "bar"


def _auto_encoding(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Auto-pick a sensible x/y encoding from the record columns."""
    cols = _columns(records)
    if not cols:
        return {}
    numeric = [c for c in cols if _is_numeric_column(records, c)]
    categorical = [c for c in cols if c not in numeric]

    if categorical and numeric:
        x = categorical[0]
        y = numeric[0]
        return {
            "x": {"field": x, "type": "nominal"},
            "y": {"field": y, "type": "quantitative"},
        }
    if len(numeric) >= 2:
        return {
            "x": {"field": numeric[0], "type": "quantitative"},
            "y": {"field": numeric[1], "type": "quantitative"},
        }
    # Fallback: first column nominal, second (if any) quantitative.
    enc: dict[str, Any] = {"x": {"field": cols[0], "type": "nominal"}}
    if len(cols) > 1:
        enc["y"] = {"field": cols[1], "type": "quantitative"}
    return enc
