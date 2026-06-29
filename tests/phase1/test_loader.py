"""Tests for the dataset loader, schema, samples, and in-process cache.

Schema + samples are the only data ever shown to the LLM (privacy boundary), so
they must stay small and strictly JSON-serializable. No network/LLM needed.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from execution import loader
from execution.loader import (
    dataframe_cache,
    extract_samples,
    extract_schema,
    get_or_load,
    load_dataset,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    dataframe_cache.clear()
    yield
    dataframe_cache.clear()


def _write_csv(path) -> str:
    csv_path = path / "sample.csv"
    csv_path.write_text(
        "id,amount,region,when\n"
        "1,10.5,north,2024-01-01\n"
        "2,20.0,south,2024-02-01\n"
        "3,,east,2024-03-01\n"
        "4,40.25,north,2024-04-01\n"
        "5,5.0,west,2024-05-01\n"
        "6,60.0,south,2024-06-01\n",
        encoding="utf-8",
    )
    return str(csv_path)


# --- load --------------------------------------------------------------------


def test_load_csv(tmp_path):
    df = load_dataset(_write_csv(tmp_path), "csv")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 6
    assert list(df.columns) == ["id", "amount", "region", "when"]


def test_load_unsupported_type_raises(tmp_path):
    with pytest.raises(ValueError):
        load_dataset(_write_csv(tmp_path), "parquet")


def test_load_xlsx(tmp_path):
    xlsx_path = tmp_path / "sample.xlsx"
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_excel(
        xlsx_path, index=False, engine="openpyxl"
    )
    df = load_dataset(str(xlsx_path), "xlsx")
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


# --- schema ------------------------------------------------------------------


def test_extract_schema_dtypes(tmp_path):
    df = load_dataset(_write_csv(tmp_path), "csv")
    schema = extract_schema(df)
    assert schema["id"].startswith("int")
    assert schema["amount"].startswith("float")
    # pandas >= 3.0 infers string columns as the `str` dtype; older versions
    # report `object`. Accept either so the schema string stays informative.
    assert schema["region"] in {"object", "str"}
    # Schema is JSON-serializable.
    json.dumps(schema)


# --- samples -----------------------------------------------------------------


def test_extract_samples_json_serializable_and_length(tmp_path):
    df = load_dataset(_write_csv(tmp_path), "csv")
    samples = extract_samples(df, n=3)
    assert len(samples) == 3
    # Must survive json.dumps with no custom encoder.
    encoded = json.dumps(samples)
    assert isinstance(encoded, str)


def test_extract_samples_default_n_is_five(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_SAMPLE_ROWS", raising=False)
    df = load_dataset(_write_csv(tmp_path), "csv")
    samples = extract_samples(df)
    assert len(samples) == 5


def test_extract_samples_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SAMPLE_ROWS", "2")
    df = load_dataset(_write_csv(tmp_path), "csv")
    assert len(extract_samples(df)) == 2


def test_extract_samples_length_min_n_rows():
    df = pd.DataFrame({"a": [1, 2]})
    assert len(extract_samples(df, n=10)) == 2


def test_extract_samples_nan_becomes_none(tmp_path):
    df = load_dataset(_write_csv(tmp_path), "csv")
    # Row index 2 (third row) has an empty `amount` -> must be None, not NaN.
    samples = extract_samples(df, n=3)
    assert samples[2]["amount"] is None
    json.dumps(samples)  # would raise on a raw NaN/np type


def test_samples_no_numpy_types_leak():
    df = pd.DataFrame(
        {
            "i": pd.Series([1, 2], dtype="int64"),
            "f": pd.Series([1.5, 2.5], dtype="float64"),
            "b": pd.Series([True, False]),
            "t": pd.to_datetime(["2024-01-01", "2024-01-02"]),
        }
    )
    samples = extract_samples(df, n=2)
    for row in samples:
        assert isinstance(row["i"], int)
        assert isinstance(row["f"], float)
        assert isinstance(row["b"], bool)
        assert isinstance(row["t"], str)  # timestamp -> isoformat string
    json.dumps(samples)


# --- cache -------------------------------------------------------------------


def test_get_or_load_caches(tmp_path):
    path = _write_csv(tmp_path)
    first = get_or_load("ds-1", path, "csv")
    second = get_or_load("ds-1", path, "csv")
    assert first is second  # same object returned from cache
    assert "ds-1" in dataframe_cache


def test_get_or_load_distinct_ids(tmp_path):
    path = _write_csv(tmp_path)
    a = get_or_load("ds-a", path, "csv")
    b = get_or_load("ds-b", path, "csv")
    assert a is not b
