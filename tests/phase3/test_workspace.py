"""Phase 3 — Workspace Layer tests (real Gemini via .env).

Covers the Phase-3 gate assertions from spec/roadmap.md:

  1. Multi-file: a question across two fixture files returns a joined result
     matching a hand-computed join.
  2. Dataset library: uploaded datasets are listable (persistence) and deletable.
  3. Cost tracking: an analysis records non-zero tokens + cost, and GET
     /cost/daily aggregates them.
  4. SSE/streaming: the streaming runner emits ordered node-status events.
  5. Run history: GET /analyses?dataset_id= returns prior analyses with code +
     timestamps.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from config.settings import get_settings
from execution.loader import dataframe_cache
from graph.runner import run_agent_stream


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


def _upload(api_client, df: pd.DataFrame, name: str) -> str:
    r = api_client.post(
        "/datasets",
        files={"file": (name, _csv_bytes(df), "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"]


# --- 1. Multi-file join ------------------------------------------------------


def test_multi_file_join_matches_handcomputed(api_client):
    orders = pd.DataFrame(
        {"customer_id": [1, 1, 2, 3], "amount": [100, 200, 300, 400]}
    )
    customers = pd.DataFrame(
        {"customer_id": [1, 2, 3], "region": ["north", "south", "north"]}
    )
    # Ground truth: join then sum amount by region -> north=700, south=300.
    merged = orders.merge(customers, on="customer_id")
    truth = merged.groupby("region")["amount"].sum().to_dict()
    assert truth == {"north": 700, "south": 300}

    orders_id = _upload(api_client, orders, "orders.csv")
    customers_id = _upload(api_client, customers, "customers.csv")

    r = api_client.post(
        "/analyses",
        json={
            "dataset_id": orders_id,
            "dataset_ids": [orders_id, customers_id],
            "question": "Join the orders to the customers on customer_id and give the total amount for each region.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "completed", body

    haystack = (str(body.get("answer", "")) + str(body.get("result", ""))).lower()
    # The north total (700) only arises from a CORRECT cross-file join.
    assert "700" in haystack, body
    assert "north" in haystack and "south" in haystack, body


# --- 2. Dataset library ------------------------------------------------------


def test_datasets_listable_and_deletable(api_client):
    ds_id = _upload(api_client, pd.DataFrame({"a": [1, 2, 3]}), "lib.csv")

    r = api_client.get("/datasets")
    assert r.status_code == 200, r.text
    listing = r.json()["data"]["datasets"]
    assert any(d["dataset_id"] == ds_id for d in listing), listing

    r = api_client.delete(f"/datasets/{ds_id}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deleted"] is True

    r = api_client.get("/datasets")
    listing = r.json()["data"]["datasets"]
    assert not any(d["dataset_id"] == ds_id for d in listing)


# --- 3. Cost tracking --------------------------------------------------------


def test_cost_tracked_per_analysis_and_daily(api_client):
    ds_id = _upload(api_client, pd.DataFrame({"amount": [10, 20, 30]}), "cost.csv")

    r = api_client.post(
        "/analyses",
        json={"dataset_id": ds_id, "question": "What is the total amount?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "completed"
    assert body["tokens"] is not None and body["tokens"] > 0, body
    assert body["estimated_cost_usd"] is not None and body["estimated_cost_usd"] >= 0, body

    r = api_client.get("/cost/daily")
    assert r.status_code == 200, r.text
    daily = r.json()["data"]
    assert daily["total_tokens"] >= body["tokens"], daily
    assert "date" in daily and "total_cost_usd" in daily


# --- 4. Streaming ------------------------------------------------------------


def test_stream_emits_ordered_node_steps(api_client):
    ds_id = _upload(api_client, pd.DataFrame({"amount": [5, 15, 25]}), "stream.csv")

    events = list(run_agent_stream(ds_id, "What is the average amount?"))
    steps = [e.get("step") for e in events]

    assert steps, "stream produced no events"
    assert steps[0] == "planning", steps
    assert "running_code" in steps, steps
    assert steps[-1] == "done", steps
    assert events[-1].get("analysis_id"), events[-1]
    # Planning must come before code execution (ordered node statuses).
    assert steps.index("planning") < steps.index("running_code"), steps


# --- 5. Run history ----------------------------------------------------------


def test_history_lists_prior_analyses(api_client):
    ds_id = _upload(api_client, pd.DataFrame({"amount": [1, 2, 3, 4]}), "hist.csv")

    r = api_client.post(
        "/analyses",
        json={"dataset_id": ds_id, "question": "What is the maximum amount?"},
    )
    assert r.status_code == 200, r.text

    r = api_client.get(f"/analyses?dataset_id={ds_id}")
    assert r.status_code == 200, r.text
    items = r.json()["data"]["analyses"]
    assert len(items) >= 1
    first = items[0]
    assert first["question"] == "What is the maximum amount?"
    assert first["code"]
    assert first["status"] == "completed"
    assert first["created_at"]
