"""Extract booking parameters from the conversation into BookingState.

STUB — implement using Anthropic JSON output (or tool-use) to parse:
    city, check_in (ISO), check_out (ISO), guests, max_price_per_night, preferences

Merge with any existing booking_in_progress (don't lose info the user gave earlier).
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from anthropic import Anthropic

from app.agent.state import AgentState, BookingState
from app.observability import logger, timed_llm_call


_PROMPT = """Extract booking parameters from the conversation. Today's date is {today}.

Return a JSON object with these keys (use null for anything not specified):
{{
  "city": string | null,                       // destination city, lowercase
  "check_in": "YYYY-MM-DD" | null,             // ISO date
  "check_out": "YYYY-MM-DD" | null,            // ISO date
  "guests": int | null,
  "max_price_per_night": number | null,         // AUD
  "preferences": [string, ...]                 // e.g. ["near beach", "gym", "pool"]
}}

Rules:
- Resolve relative dates ("next weekend", "this Friday") to absolute dates.
- If the user says "2 nights from Fri", set check_in and check_out accordingly.
- Do NOT invent values. If the user hasn't said it, the field is null.

Reply with ONLY the JSON object, no prose, no markdown."""


def _client() -> Anthropic:
    return Anthropic()


def _merge(existing: BookingState | None, incoming: dict) -> BookingState:
    """Merge new extraction into existing booking state, preferring non-null incoming."""
    out: BookingState = dict(existing or {})  # type: ignore[assignment]
    out.setdefault("preferences", [])
    for k, v in incoming.items():
        if v is None or v == [] or v == "":
            continue
        if k == "preferences" and isinstance(v, list):
            # Union preferences
            prev = out.get("preferences") or []
            out["preferences"] = sorted(set(prev) | set(v))
        else:
            out[k] = v
    return out


async def run(state: AgentState) -> dict:
    model = os.getenv("AGENT_MODEL", "claude-sonnet-4-6")
    messages = state.get("messages", [])
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages[-10:])

    prompt = _PROMPT.format(today=datetime.utcnow().date().isoformat())

    with timed_llm_call(model=model, node="extract_params") as usage:
        resp = _client().messages.create(
            model=model,
            max_tokens=300,
            system=prompt,
            messages=[{"role": "user", "content": f"Conversation:\n{convo}"}],
        )
        usage["input_tokens"] = resp.usage.input_tokens
        usage["output_tokens"] = resp.usage.output_tokens

    raw = resp.content[0].text.strip() if resp.content else "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("extract_params_parse_fail", raw=raw)
        parsed = {}

    merged = _merge(state.get("booking_in_progress"), parsed)
    logger.info("extract_params", merged=merged)
    return {"booking_in_progress": merged}
