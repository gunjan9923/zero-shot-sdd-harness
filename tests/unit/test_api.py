"""API contract tests that do NOT invoke the LLM.

The legacy `/runs` route was the skeleton's `transform_text` slot; it is no
longer mounted (the runner is now `run_agent(dataset_id, question)` for the
data-analysis agent), so its tests were removed. The full datasets/analyses
happy path runs against real Gemini in tests/phase1/test_api.py.
"""


def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_runs_route_removed(api_client):
    # The deprecated skeleton route must be gone, not silently broken.
    r = api_client.post("/runs", json={"input_text": "test"})
    assert r.status_code == 404


def test_analysis_blank_question_rejected_without_llm(api_client):
    # Validation happens before run_agent, so no LLM key is needed here.
    r = api_client.post("/analyses", json={"dataset_id": "anything", "question": "   "})
    assert r.status_code == 400
    assert r.json()["detail"]["message"] == "Missing question"


def test_analysis_unknown_dataset_rejected_without_llm(api_client):
    r = api_client.post(
        "/analyses", json={"dataset_id": "does-not-exist", "question": "hi"}
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_REQUEST"


def test_get_unknown_analysis_404(api_client):
    r = api_client.get("/analyses/nope")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND"


def test_list_datasets_empty_ok(api_client):
    r = api_client.get("/datasets")
    assert r.status_code == 200
    assert r.json()["data"]["datasets"] == []
