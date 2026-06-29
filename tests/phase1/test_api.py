"""Phase 1 API contract tests — FastAPI TestClient against the REAL Gemini API.

Covers the datasets + analyses slice end-to-end:
  * POST /datasets with an in-memory CSV -> 200, schema + row_count.
  * POST /analyses -> 200, status completed, real computed sum (ground truth
    via pandas), non-empty code.
  * GET /analyses/{id} -> 200 same shape.
  * Error/edge paths: blank question (400), unknown dataset_id (400),
    unknown analysis (404), unsupported file type (400).

DB is isolated by the autouse ``_isolated_db`` fixture in tests/conftest.py
(temp SQLite wired into the session module — the production driver for this
single-user tool). The Gemini key is loaded from .env via get_settings();
tests skip only if the key is genuinely absent.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from config.settings import get_settings
from execution.loader import dataframe_cache


@pytest.fixture(autouse=True)
def _require_gemini():
    if not get_settings().gemini_api_key:
        pytest.skip("AGENT_GEMINI_API_KEY not set in .env — required for the real-Gemini run")


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    dataframe_cache.clear()
    yield
    dataframe_cache.clear()


def _csv_bytes(rows: list[dict]) -> tuple[bytes, pd.DataFrame]:
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8"), df


# --- Happy path: upload + analyse against real Gemini ------------------------


def test_upload_dataset_returns_schema_and_row_count(api_client):
    rows = [
        {"id": 1, "region": "north", "amount": 10.5},
        {"id": 2, "region": "south", "amount": 20.0},
        {"id": 3, "region": "east", "amount": 30.25},
    ]
    csv, _df = _csv_bytes(rows)

    r = api_client.post(
        "/datasets",
        files={"file": ("sales.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["dataset_id"]
    assert data["name"] == "sales.csv"
    assert data["file_type"] == "csv"
    assert data["row_count"] == 3
    # Schema is {column: pandas-dtype-string}. Numeric dtypes are stable; the
    # text column's label varies by pandas version ("object" or "str").
    schema = data["schema"]
    assert schema["id"] == "int64"
    assert schema["amount"] == "float64"
    assert schema["region"] in ("object", "str")
    assert isinstance(data["samples"], list) and len(data["samples"]) == 3
    # Phase 2: upload now auto-profiles the dataset (was a None stub in Phase 1).
    assert isinstance(data["profile"], dict)
    assert data["profile"]["amount"]["missing"] == 0


def test_analysis_computes_real_sum_and_get_roundtrip(api_client):
    rows = [
        {"id": 1, "amount": 10.5},
        {"id": 2, "amount": 20.0},
        {"id": 3, "amount": 30.25},
        {"id": 4, "amount": 40.0},
        {"id": 5, "amount": 5.25},
    ]
    csv, df = _csv_bytes(rows)
    expected_sum = float(df["amount"].sum())  # ground truth via pandas

    up = api_client.post("/datasets", files={"file": ("nums.csv", csv, "text/csv")})
    assert up.status_code == 200, up.text
    dataset_id = up.json()["data"]["dataset_id"]

    r = api_client.post(
        "/analyses",
        json={"dataset_id": dataset_id, "question": "what is the total of amount?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "completed", body
    assert body["code"] and "df" in body["code"], f"code missing/odd: {body.get('code')!r}"
    assert body["error"] is None

    # The real sum must surface in result and/or answer (not hallucinated).
    haystack = f"{body.get('result')} || {body.get('answer')}"
    assert (
        str(round(expected_sum, 2)) in haystack
        or str(expected_sum) in haystack
        or f"{expected_sum:.1f}" in haystack
    ), f"expected sum {expected_sum} not reflected in result/answer: {haystack!r}"

    # GET round-trip returns the same shape.
    analysis_id = body["analysis_id"]
    g = api_client.get(f"/analyses/{analysis_id}")
    assert g.status_code == 200, g.text
    gbody = g.json()["data"]
    assert gbody["analysis_id"] == analysis_id
    assert gbody["status"] == "completed"
    assert gbody["code"] == body["code"]
    assert set(gbody.keys()) == set(body.keys())


# --- GET /datasets stub ------------------------------------------------------


def test_list_datasets_returns_list(api_client):
    r = api_client.get("/datasets")
    assert r.status_code == 200, r.text
    assert "datasets" in r.json()["data"]
    assert isinstance(r.json()["data"]["datasets"], list)


# --- Error / edge paths ------------------------------------------------------


def test_analysis_blank_question_rejected(api_client):
    csv, _ = _csv_bytes([{"id": 1, "amount": 1.0}])
    up = api_client.post("/datasets", files={"file": ("x.csv", csv, "text/csv")})
    dataset_id = up.json()["data"]["dataset_id"]

    r = api_client.post("/analyses", json={"dataset_id": dataset_id, "question": "   "})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["message"] == "Missing question"


def test_analysis_unknown_dataset_rejected(api_client):
    r = api_client.post(
        "/analyses",
        json={"dataset_id": "does-not-exist", "question": "anything?"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "BAD_REQUEST"


def test_get_unknown_analysis_404(api_client):
    r = api_client.get("/analyses/nonexistent-id")
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "NOT_FOUND"


def test_upload_unsupported_file_type_rejected(api_client):
    r = api_client.post(
        "/datasets",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "BAD_FILE"


def test_upload_unparseable_excel_rejected(api_client):
    # .xlsx extension but bytes are not a valid workbook -> parse error -> 400.
    r = api_client.post(
        "/datasets",
        files={
            "file": (
                "broken.xlsx",
                b"this is not a real xlsx file",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "BAD_FILE"
