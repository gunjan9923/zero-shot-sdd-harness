"""Full-data correctness gate (the agent's headline success criterion).

Proves the agent computes its answer over the FULL DataFrame locally, not over
the bounded sample rows it sees in the prompt. The fixture is engineered so the
first 5 rows (the only rows the LLM ever sees) have an aggregate that is wildly
different from the full-column aggregate — so an answer derived from samples
would be off by orders of magnitude, while a real full-data computation matches
the pandas ground truth exactly.

Runs against the REAL Gemini API (keys from .env). SQLite is the production
driver for this single-user local tool, so the test uses SQLite by design.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from db import session as session_module
from db.models import AnalysisRow, Base, DatasetRow
from execution.loader import (
    dataframe_cache,
    extract_samples,
    extract_schema,
    load_dataset,
)

N_ROWS = 200_000


@pytest.fixture(autouse=True)
def _require_gemini():
    if not get_settings().gemini_api_key:
        pytest.skip("AGENT_GEMINI_API_KEY not set in .env — required for the real-Gemini run")


@pytest.fixture(autouse=True)
def _clear_cache():
    dataframe_cache.clear()
    yield
    dataframe_cache.clear()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
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


def _make_large_dataset(tmp_path, engine) -> tuple[str, pd.DataFrame]:
    """A 200k-row CSV whose first 5 rows are deliberately unrepresentative.

    - First 5 rows: amount = 1.0 each (sample sum = 5.0, sample mean = 1.0).
    - Remaining 199,995 rows: amount = 1000.0 each.
    Full sum is ~200 million; an answer based on the 5 visible samples would be
    ~5 — three orders of magnitude off. Only a true full-data computation can
    match the pandas ground truth.
    """
    amounts = [1.0] * 5 + [1000.0] * (N_ROWS - 5)
    df = pd.DataFrame(
        {
            "id": range(1, N_ROWS + 1),
            "region": (["north"] * 5) + (["south"] * (N_ROWS - 5)),
            "amount": amounts,
        }
    )
    csv_path = tmp_path / "big.csv"
    df.to_csv(csv_path, index=False)

    loaded = load_dataset(str(csv_path), "csv")
    schema = extract_schema(loaded)
    samples = extract_samples(loaded)  # bounded — first 5 rows only

    # Sanity: the samples really are unrepresentative (sum over samples == 5).
    sample_sum = sum(float(r["amount"]) for r in samples)
    assert sample_sum == 5.0, f"sample fixture unexpected: sample_sum={sample_sum}"

    with Session(engine) as s:
        ds = DatasetRow(
            name="big.csv",
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


def test_agent_computes_over_full_data_not_samples(isolated_db, tmp_path):
    from graph.runner import run_agent

    dataset_id, df = _make_large_dataset(tmp_path, isolated_db)

    full_sum = float(df["amount"].sum())          # ground truth ~ 199_995_005.0
    sample_only_sum = 5.0                           # what a sample-based guess yields
    assert full_sum > 100_000_000, full_sum        # the two answers differ by ~1e8

    run_id = run_agent(dataset_id, "What is the total of the amount column?")

    with Session(isolated_db) as s:
        analysis = s.get(AnalysisRow, run_id)

    assert analysis is not None
    assert analysis.status == "completed", (
        f"status={analysis.status} error={analysis.error_message}"
    )
    assert analysis.code and "df" in analysis.code, "code should operate on the df DataFrame"

    # The persisted numeric result must equal the FULL-data pandas sum, not the
    # sample-based number. Parse the result and compare numerically (robust to
    # int/float/locale formatting differences in the prose).
    result_json = analysis.result_json or ""
    parsed = json.loads(result_json) if result_json else None
    assert parsed is not None, f"no result persisted: {result_json!r}"

    value = parsed
    if isinstance(parsed, dict):
        # finalize may wrap a scalar; pull the single numeric leaf if so.
        nums = [v for v in parsed.values() if isinstance(v, (int, float))]
        value = nums[0] if len(nums) == 1 else parsed
    assert isinstance(value, (int, float)), f"expected a numeric result, got {value!r}"

    assert abs(float(value) - full_sum) < 1.0, (
        f"agent returned {value}, expected full-data sum {full_sum} "
        f"(sample-only sum would be {sample_only_sum}) — agent did not compute over full data"
    )
