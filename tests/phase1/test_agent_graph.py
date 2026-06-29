"""End-to-end agent-graph test against the REAL Gemini API.

Builds a temp CSV + DatasetRow, runs ``run_agent`` for a real question, and
asserts the agent actually computed the answer (not hallucinated): the persisted
result/answer reflect the true sum computed with pandas directly.

Privacy boundary: a happy-path assertion also confirms the logged LLM prompt
payload contains ONLY schema + samples (no raw rows).
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from db.models import AnalysisRow, Base, DatasetRow
from db import session as session_module
from execution.loader import dataframe_cache, extract_samples, extract_schema, load_dataset


@pytest.fixture(autouse=True)
def _require_gemini():
    s = get_settings()
    if not s.gemini_api_key:
        pytest.skip("AGENT_GEMINI_API_KEY not set in .env — required for the real-Gemini run")


@pytest.fixture(autouse=True)
def _clear_cache():
    dataframe_cache.clear()
    yield
    dataframe_cache.clear()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Temp SQLite DB wired into the session module (production driver)."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AGENT_DATABASE_URL", f"sqlite:///{db_path}")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(session_module, "_engine", engine)
    monkeypatch.setattr(session_module, "_SessionLocal", factory)
    monkeypatch.setattr(session_module, "init_db", lambda: None)
    yield engine
    engine.dispose()


def _make_dataset(tmp_path, engine, rows: list[dict]) -> tuple[str, pd.DataFrame]:
    """Write a temp CSV, create a DatasetRow, return (dataset_id, df)."""
    df = pd.DataFrame(rows)
    csv_path = tmp_path / "data.csv"
    df.to_csv(csv_path, index=False)

    loaded = load_dataset(str(csv_path), "csv")
    schema = extract_schema(loaded)
    samples = extract_samples(loaded)

    with Session(engine) as s:
        ds = DatasetRow(
            name="data.csv",
            file_path=str(csv_path),
            file_type="csv",
            row_count=len(df),
            schema_json=json.dumps(schema),
            samples_json=json.dumps(samples),
            size_bytes=csv_path.stat().st_size,
        )
        s.add(ds)
        s.commit()
        dataset_id = ds.id
    return dataset_id, loaded


# --- Happy path: real computed sum -------------------------------------------


def test_agent_computes_real_sum(isolated_db, tmp_path):
    from graph.runner import run_agent

    rows = [
        {"id": 1, "region": "north", "amount": 10.5},
        {"id": 2, "region": "south", "amount": 20.0},
        {"id": 3, "region": "east", "amount": 30.25},
        {"id": 4, "region": "north", "amount": 40.0},
        {"id": 5, "region": "west", "amount": 5.25},
    ]
    dataset_id, df = _make_dataset(tmp_path, isolated_db, rows)
    expected_sum = float(df["amount"].sum())  # ground truth via pandas directly

    run_id = run_agent(dataset_id, "What is the total of the amount column?")

    with Session(isolated_db) as s:
        analysis = s.get(AnalysisRow, run_id)

    assert analysis is not None
    assert analysis.status == "completed", f"status={analysis.status} error={analysis.error_message}"
    assert analysis.code and "df" in analysis.code, "code should reference the df DataFrame"
    assert analysis.error_message is None
    assert analysis.answer and len(analysis.answer) > 0

    # The computed result must reflect the REAL sum (not hallucinated).
    result_json = analysis.result_json or ""
    assert str(round(expected_sum, 2)) in result_json or str(expected_sum) in result_json or (
        f"{expected_sum:.1f}" in result_json
    ), f"expected sum {expected_sum} not found in result_json={result_json!r}"


def test_privacy_boundary_logs_schema_and_samples_only(isolated_db, tmp_path, capsys):
    """The logged LLM prompt payload must carry schema+samples, never raw rows
    beyond the bounded sample set."""
    from graph.runner import run_agent

    # A secret value that appears ONLY in a non-sampled row (row index > 5).
    rows = [{"id": i, "amount": float(i)} for i in range(1, 6)]
    rows.append({"id": 999, "amount": 123456.0})  # 6th row — outside default 5 samples
    dataset_id, _ = _make_dataset(tmp_path, isolated_db, rows)

    run_agent(dataset_id, "What is the total of amount?")

    captured = capsys.readouterr().out
    assert "llm_call" in captured, "expected an llm_call log line for the prompt payload"
    # The non-sampled row's distinctive value must never appear in any prompt.
    assert "123456" not in captured, "raw non-sampled row leaked into an LLM prompt — privacy boundary breached"


# --- Edge case: empty-ish question over a valid column ------------------------


def test_agent_handles_count_question(isolated_db, tmp_path):
    from graph.runner import run_agent

    rows = [{"id": i, "amount": float(i)} for i in range(1, 8)]
    dataset_id, df = _make_dataset(tmp_path, isolated_db, rows)
    expected_count = len(df)

    run_id = run_agent(dataset_id, "How many rows are in the dataset?")

    with Session(isolated_db) as s:
        analysis = s.get(AnalysisRow, run_id)

    assert analysis.status == "completed", f"error={analysis.error_message}"
    assert str(expected_count) in (analysis.result_json or "") or str(expected_count) in (
        analysis.answer or ""
    ), f"expected count {expected_count} not reflected; result={analysis.result_json} answer={analysis.answer}"


# --- Error path: unknown dataset --------------------------------------------


def test_run_agent_unknown_dataset_raises(isolated_db, tmp_path):
    from graph.runner import run_agent

    with pytest.raises(ValueError, match="dataset not found"):
        run_agent("does-not-exist", "anything?")
