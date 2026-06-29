"""Server-Sent Events stream for live analysis progress (Phase 3).

`POST /analyses/stream` runs the agent and streams ordered node-status events
(`planning`, `running_code`, `building_chart`, …) followed by a terminal
`done` event carrying the ``analysis_id``. The client then fetches the full
analysis via `GET /analyses/{analysis_id}`.

Why POST (not the originally-sketched GET-by-id): the run is created and
executed in one shot, so the question must arrive with the request. The whole
synchronous generator runs in a single worker thread (so per-run token-usage
context stays consistent) and feeds events to the async response via a queue.
"""

from __future__ import annotations

import asyncio
import json
import threading

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from domain.analysis import AnalysisRequest
from graph.runner import run_agent_stream
from observability.events import get_logger

router = APIRouter()
_log = get_logger("api.stream")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/analyses/stream")
async def stream_analysis(req: AnalysisRequest) -> StreamingResponse:
    question = (req.question or "").strip()

    async def event_source():
        if not question:
            yield _sse({"step": "error", "message": "Missing question"})
            return

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def produce():
            try:
                for event in run_agent_stream(
                    req.dataset_id,
                    question,
                    dataset_ids=req.dataset_ids,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:  # noqa: BLE001 - surface as a stream error
                _log.error("stream_failed", dataset_id=req.dataset_id, error=str(exc))
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"step": "error", "message": str(exc)}
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        threading.Thread(target=produce, daemon=True).start()

        while True:
            event = await queue.get()
            if event is sentinel:
                break
            yield _sse(event)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
