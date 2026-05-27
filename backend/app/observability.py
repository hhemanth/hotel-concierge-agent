"""Structured logging + LLM call tracking.

Every LLM call should go through `track_llm_call` so we have a per-request
cost and token report. This is what makes the 'production-grade' claim
defensible in the demo.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

import structlog
from pythonjsonlogger import jsonlogger


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def configure_logging() -> None:
    """Wire structlog + JSON logging. Call once at process start."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "json").lower()

    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(jsonlogger.JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s"
        ))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s"
        ))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Per-request cost / token tracking
# ---------------------------------------------------------------------------

@dataclass
class LLMCall:
    model: str
    node: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


@dataclass
class RequestStats:
    request_id: str
    calls: list[LLMCall] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "n_calls": len(self.calls),
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cost_usd": round(self.total_cost_usd, 6),
            "calls": [c.__dict__ for c in self.calls],
        }


_current_stats: ContextVar[RequestStats | None] = ContextVar("_current_stats", default=None)


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[RequestStats]:
    """Bind a RequestStats to the current async/thread context.

    Use in FastAPI dependencies or LangGraph runs to scope LLM cost tracking
    to a single user turn.
    """
    rid = request_id or uuid.uuid4().hex[:12]
    stats = RequestStats(request_id=rid)
    token = _current_stats.set(stats)
    structlog.contextvars.bind_contextvars(request_id=rid)
    try:
        yield stats
    finally:
        _current_stats.reset(token)
        structlog.contextvars.unbind_contextvars("request_id")


# ---------------------------------------------------------------------------
# Pricing table (USD per 1K tokens). Update as Anthropic changes prices.
# ---------------------------------------------------------------------------

# These are illustrative — update from https://www.anthropic.com/pricing when you ship.
_PRICING: dict[str, tuple[float, float]] = {
    # model_substring : (input_per_1k, output_per_1k)
    "claude-sonnet-4": (0.003, 0.015),
    "claude-haiku-4":  (0.0008, 0.004),
    "claude-opus-4":   (0.015, 0.075),
    "text-embedding-3-small": (0.00002, 0.0),
}


def _price_for(model: str, input_tokens: int, output_tokens: int) -> float:
    for prefix, (in_price, out_price) in _PRICING.items():
        if prefix in model:
            return (input_tokens / 1000) * in_price + (output_tokens / 1000) * out_price
    return 0.0


def track_llm_call(
    *, model: str, node: str, input_tokens: int, output_tokens: int, latency_ms: float
) -> None:
    """Record an LLM call against the current request context.

    Safe to call outside a request_context — the call is logged but not aggregated.
    """
    cost = _price_for(model, input_tokens, output_tokens)
    call = LLMCall(model=model, node=node, input_tokens=input_tokens,
                   output_tokens=output_tokens, cost_usd=cost, latency_ms=latency_ms)
    stats = _current_stats.get()
    if stats is not None:
        stats.calls.append(call)
    logger.info("llm_call", **call.__dict__)


@contextmanager
def timed_llm_call(*, model: str, node: str) -> Iterator[dict[str, int]]:
    """Convenience: time a block and report tokens after.

    Usage:
        with timed_llm_call(model=..., node=...) as usage:
            resp = client.messages.create(...)
            usage["input_tokens"]  = resp.usage.input_tokens
            usage["output_tokens"] = resp.usage.output_tokens
    """
    usage = {"input_tokens": 0, "output_tokens": 0}
    start = time.perf_counter()
    try:
        yield usage
    finally:
        latency_ms = (time.perf_counter() - start) * 1000
        track_llm_call(
            model=model, node=node,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            latency_ms=latency_ms,
        )
