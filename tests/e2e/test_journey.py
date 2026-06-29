"""End-to-end primary-journey test against the LIVE server + REAL Gemini.

Boots the app exactly as the user runs it (`uv run python -m src`), waits for
readiness, then walks the full Phase-1 journey over real HTTP:
  1. the built frontend renders at /app/ (styled, not a bare 200),
  2. upload a CSV  -> POST /datasets  (schema + row_count returned),
  3. ask a question -> POST /analyses (real Gemini plans + writes + RUNS pandas),
  4. the answer reflects the REAL computed total (fixture sum = 600), and the
     exact pandas code is returned for the collapsible panel,
  5. GET /analyses/{id} returns the same persisted result.

SQLite is the production driver for this single-user local tool, so the live
run uses the configured SQLite DB. Requires AGENT_GEMINI_API_KEY in .env.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "sales.csv"
EXPECTED_SUM = 600  # sum of the amount column in fixtures/sales.csv


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _gemini_key_present() -> bool:
    if os.environ.get("AGENT_GEMINI_API_KEY"):
        return True
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("AGENT_GEMINI_API_KEY=") and line.split("=", 1)[1].strip():
                return True
    return False


pytestmark = [
    pytest.mark.skipif(httpx is None, reason="httpx not installed"),
    pytest.mark.skipif(
        not _gemini_key_present(),
        reason="AGENT_GEMINI_API_KEY not set in .env — required for the real-Gemini live run",
    ),
]


@pytest.fixture(scope="module")
def live_server():
    port = _free_port()
    env = dict(os.environ)
    env["PORT"] = str(port)
    # Isolate the live DB so the test never touches the user's data/agent.db.
    db_path = REPO_ROOT / "data" / f"e2e_test_{port}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    env["AGENT_DATABASE_URL"] = f"sqlite:///./data/{db_path.name}"

    # Launch with the SAME interpreter running the tests (the project venv),
    # not a nested `uv run` — nesting `uv run` inside `uv run pytest` serializes
    # on the uv environment lock and can stall the child's startup.
    proc = subprocess.Popen(
        [sys.executable, "-m", "src"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=open(REPO_ROOT / "data" / f"e2e_srv_{port}.log", "w"),
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    # Wait for readiness (init_db runs in lifespan).
    deadline = time.time() + 60
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            raise RuntimeError(f"server exited early (code {proc.returncode}):\n{out}")
        try:
            r = httpx.get(f"{base}/health", timeout=2)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(1)
    if not ready:
        proc.terminate()
        raise RuntimeError("server did not become ready within 60s")

    yield base

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass


def test_frontend_renders_at_app(live_server):
    """The built static export is served and styled at /app/ (not a bare 200)."""
    r = httpx.get(f"{live_server}/app/", timeout=10, follow_redirects=True)
    assert r.status_code == 200, r.status_code
    html = r.text
    # Real rendered content + the basePath-prefixed CSS bundle (proves styled).
    assert "/app/_next/static/css/" in html, "no built CSS bundle referenced — page is unstyled"
    # A labelled stub must be present so the user never mistakes it for a bug.
    assert "coming soon" in html.lower(), "expected at least one labelled 'coming soon' stub"


def test_full_journey_upload_ask_answer(live_server):
    # 1. Upload the fixture CSV (real POST /datasets).
    with FIXTURE.open("rb") as fh:
        up = httpx.post(
            f"{live_server}/datasets",
            files={"file": ("sales.csv", fh, "text/csv")},
            timeout=30,
        )
    assert up.status_code == 200, f"{up.status_code}: {up.text}"
    ds = up.json()["data"]
    assert ds["dataset_id"]
    assert ds["row_count"] == 5
    assert "amount" in ds["schema"], ds["schema"]
    dataset_id = ds["dataset_id"]

    # 2. Ask a question -> real Gemini plans + writes + runs pandas locally.
    ask = httpx.post(
        f"{live_server}/analyses",
        json={"dataset_id": dataset_id, "question": "What is the total of the amount column?"},
        timeout=180,
    )
    assert ask.status_code == 200, f"{ask.status_code}: {ask.text}"
    a = ask.json()["data"]
    assert a["status"] == "completed", a
    # 3. The exact code that ran is returned (collapsible panel content) and real.
    assert a["code"] and "df" in a["code"], a["code"]
    # 4. The answer reflects the REAL computed total (600), not a hallucination.
    combined = f"{a['answer']} {a['result']}"
    assert str(EXPECTED_SUM) in combined or "600.0" in combined, (
        f"expected total {EXPECTED_SUM} in answer/result; got answer={a['answer']!r} result={a['result']!r}"
    )

    # 5. GET the analysis back -> same persisted result.
    got = httpx.get(f"{live_server}/analyses/{a['analysis_id']}", timeout=10)
    assert got.status_code == 200, got.text
    g = got.json()["data"]
    assert g["analysis_id"] == a["analysis_id"]
    assert g["status"] == "completed"
