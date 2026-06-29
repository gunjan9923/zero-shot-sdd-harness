"""Per-run LLM token-usage accumulation + cost estimation (Phase 3).

The agent makes several Gemini calls per question (plan, generate_code, possibly
retries, finalize, chart, followups). To surface "tokens + cost per question",
each call's usage is added to a context-local accumulator; the runner resets it
before a run and reads the totals afterwards.

A context variable (not a module global) keeps concurrent requests isolated even
though a single run is synchronous.
"""

from __future__ import annotations

import contextvars
import os

# {"prompt_tokens": int, "completion_tokens": int} accumulated for the current run.
_usage: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "_usage", default=None
)


def reset_usage() -> None:
    """Begin accumulating for a new run (clears any prior totals)."""
    _usage.set({"prompt_tokens": 0, "completion_tokens": 0})


def add_usage(prompt_tokens: int, completion_tokens: int) -> None:
    """Add one LLM call's token counts to the current run's totals."""
    current = _usage.get()
    if current is None:
        current = {"prompt_tokens": 0, "completion_tokens": 0}
        _usage.set(current)
    current["prompt_tokens"] += int(prompt_tokens or 0)
    current["completion_tokens"] += int(completion_tokens or 0)


def get_usage() -> dict[str, int]:
    """Return the accumulated totals for the current run (zeros if none)."""
    current = _usage.get()
    if current is None:
        return {"prompt_tokens": 0, "completion_tokens": 0}
    return dict(current)


def _price(env_name: str, default: float) -> float:
    raw = os.environ.get(env_name, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            return default
    return default


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from token counts.

    Per-1K-token prices are configurable via ``AGENT_COST_PER_1K_INPUT`` /
    ``AGENT_COST_PER_1K_OUTPUT`` (USD). Defaults are conservative Gemini-pro-class
    estimates; this is a best-effort cost meter, not a billing source of truth.
    """
    in_price = _price("AGENT_COST_PER_1K_INPUT", 0.00125)
    out_price = _price("AGENT_COST_PER_1K_OUTPUT", 0.005)
    return round(
        (int(prompt_tokens or 0) / 1000.0) * in_price
        + (int(completion_tokens or 0) / 1000.0) * out_price,
        6,
    )
