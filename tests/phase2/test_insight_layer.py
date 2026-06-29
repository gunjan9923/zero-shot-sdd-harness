"""Phase 2 — Insight Layer tests (real Gemini via .env).

Covers the four Phase-2 gate assertions from spec/roadmap.md:

  1. Auto-profiling: uploading a fixture produces a profile with correct dtypes
     and missing-value counts (matched against a hand-computed pandas profile).
  2. Charts: a question that warrants a chart returns a valid Vega-Lite spec
     whose embedded data was computed LOCALLY (matches the pandas group-by).
  3. Follow-ups: each answer returns 2–3 non-empty follow-up suggestions.
  4. Conversational follow-up: a follow-up referencing prior context ("break
     THAT down by region") resolves using prior-turn history.

DB isolation + the FastAPI ``api_client`` fixture come from tests/conftest.py.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from config.settings import get_settings
from execution.loader import dataframe_cache
from execution.profiler import profile_dataset


@pytest.fixture(autouse=True)
def _require_gemini():
    if not get_settings().gemini_api_key:
        pytest.skip("AGENT_GEMINI_API_KEY not set in .env — required for the real-Gemini run")


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    dataframe_cache.clear()
    yield
    dataframe_cache.clear()


def _csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def _upload(api_client, df: pd.DataFrame) -> dict:
    csv = _csv_bytes(df)
    r = api_client.post(
        "/datasets",
        files={"file": ("data.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _sales_df() -> pd.DataFrame:
    # 'amount' has one missing value; 'region' is categorical with a known
    # distribution; 'note' is an object column with a missing value too.
    return pd.DataFrame(
        {
            "order_id": [1, 2, 3, 4, 5, 6],
            "region": ["north", "south", "north", "east", "south", "north"],
            "amount": [10.0, 20.0, 30.0, None, 40.0, 50.0],
            "note": ["a", None, "b", "c", "d", "e"],
        }
    )


# --- 1. Auto-profiling -------------------------------------------------------


def test_upload_returns_profile_matching_handcomputed(api_client):
    df = _sales_df()
    data = _upload(api_client, df)

    profile = data.get("profile")
    assert profile is not None, "upload must return a non-null profile (Phase 2)"

    expected = profile_dataset(df)
    # dtypes
    assert profile["amount"]["type"] == expected["amount"]["type"] == "float64"
    assert profile["region"]["type"] == expected["region"]["type"]

    # missing-value counts are exact, over the FULL frame
    assert profile["amount"]["missing"] == 1
    assert profile["note"]["missing"] == 1
    assert profile["region"]["missing"] == 0
    assert profile["order_id"]["missing"] == 0

    # numeric stats present and correct on the non-null values
    assert profile["amount"]["min"] == 10.0
    assert profile["amount"]["max"] == 50.0

    # categorical distinct count
    assert profile["region"]["distinct"] == 3


def test_profile_endpoint_returns_profile(api_client):
    df = _sales_df()
    data = _upload(api_client, df)
    dataset_id = data["dataset_id"]

    r = api_client.get(f"/datasets/{dataset_id}/profile")
    assert r.status_code == 200, r.text
    profile = r.json()["data"]["profile"]
    assert profile is not None
    assert profile["amount"]["missing"] == 1


# --- 2. Charts ---------------------------------------------------------------


def test_breakdown_question_returns_valid_vega_lite_with_local_data(api_client):
    df = _sales_df()
    data = _upload(api_client, df)
    dataset_id = data["dataset_id"]

    r = api_client.post(
        "/analyses",
        json={
            "dataset_id": dataset_id,
            "question": "Show me the total amount for each region as a bar chart.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "completed"

    spec = body["chart_spec"]
    assert spec is not None, "a breakdown/charting question must return a chart spec"
    assert "vega-lite" in spec.get("$schema", ""), spec
    assert "mark" in spec and "encoding" in spec
    values = spec.get("data", {}).get("values")
    assert isinstance(values, list) and values, "spec must embed locally-computed data"

    # The embedded data is the REAL local group-by, not anything the LLM made up.
    truth = df.groupby("region")["amount"].sum().dropna().to_dict()
    got: dict[str, float] = {}
    for rec in values:
        # find the region-like key and the numeric value in each record
        region = next((v for v in rec.values() if isinstance(v, str)), None)
        number = next(
            (v for v in rec.values() if isinstance(v, (int, float)) and not isinstance(v, bool)),
            None,
        )
        if region is not None and number is not None:
            got[region] = float(number)

    assert got, f"could not extract region->amount from embedded values: {values}"
    for region, total in got.items():
        assert region in truth, f"unexpected region {region} in chart data"
        assert abs(truth[region] - total) < 1e-6, (region, total, truth[region])


# --- 3. Follow-up suggestions ------------------------------------------------


def test_answer_returns_two_or_three_followups(api_client):
    df = _sales_df()
    data = _upload(api_client, df)
    dataset_id = data["dataset_id"]

    r = api_client.post(
        "/analyses",
        json={"dataset_id": dataset_id, "question": "What is the total amount?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "completed"

    followups = body["followups"]
    assert isinstance(followups, list), "followups must be a list"
    assert 2 <= len(followups) <= 3, f"expected 2-3 followups, got {followups}"
    assert all(isinstance(f, str) and f.strip() for f in followups)


# --- 4. Conversational follow-up (uses prior-turn context) -------------------


def test_followup_resolves_prior_context(api_client):
    df = _sales_df()
    data = _upload(api_client, df)
    dataset_id = data["dataset_id"]

    # Turn 1 establishes the referent ("amount").
    r1 = api_client.post(
        "/analyses",
        json={"dataset_id": dataset_id, "question": "What is the total amount?"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["status"] == "completed"

    # Turn 2 uses a pronoun that only resolves with the prior turn's context.
    r2 = api_client.post(
        "/analyses",
        json={"dataset_id": dataset_id, "question": "Now break that down by region."},
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()["data"]
    assert body2["status"] == "completed", body2

    # The contextual answer must reflect a per-region breakdown of amount.
    truth = df.groupby("region")["amount"].sum().dropna().to_dict()
    haystack = (str(body2.get("answer", "")) + str(body2.get("result", ""))).lower()
    # At least the region labels must appear — proves "that" -> amount-by-region.
    assert "north" in haystack and "south" in haystack, body2
    # And a real number from the breakdown should be present somewhere.
    assert any(str(int(v)) in haystack for v in truth.values()), (haystack, truth)
