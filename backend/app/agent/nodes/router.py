"""Router node: classify the latest user message into an intent.

Returns one of: info | booking | smalltalk | unknown.

Implementation is a small Haiku call with JSON output. We deliberately keep
this cheap so the cost stays low — most turns are info questions.
"""

from __future__ import annotations

import json
import os

from anthropic import Anthropic

from app.agent.state import AgentState, Intent
from app.observability import logger, timed_llm_call


_PROMPT = """You are an intent classifier for a hotel concierge chatbot. \
Read the conversation and classify the user's LATEST message into exactly one of:

- "info": the user is asking a question about a property, amenities, FAQs, policies, location, etc.
- "booking": the user wants to start, modify, or confirm a booking (find rooms, change dates, cancel, etc.)
- "smalltalk": greetings, thanks, off-topic chit-chat
- "unknown": cannot determine

Reply with ONLY a JSON object like {"intent": "..."}. No prose, no markdown."""


def _client() -> Anthropic:
    return Anthropic()


async def run(state: AgentState) -> dict:
    model = os.getenv("ROUTER_MODEL", "claude-haiku-4-5-20251001")
    messages = state.get("messages", [])

    # Build a compact conversation for the classifier.
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages[-6:])
    user_block = f"Conversation:\n{convo}\n\nClassify the LAST user message."

    intent: Intent = "unknown"
    with timed_llm_call(model=model, node="router") as usage:
        resp = _client().messages.create(
            model=model,
            max_tokens=64,
            system=_PROMPT,
            messages=[{"role": "user", "content": user_block}],
        )
        usage["input_tokens"] = resp.usage.input_tokens
        usage["output_tokens"] = resp.usage.output_tokens

    raw = resp.content[0].text.strip() if resp.content else ""
    try:
        parsed = json.loads(raw)
        candidate = parsed.get("intent", "unknown").strip().lower()
        if candidate in ("info", "booking", "smalltalk", "unknown"):
            intent = candidate  # type: ignore[assignment]
    except json.JSONDecodeError:
        logger.warning("router_parse_fail", raw=raw)

    logger.info("router_intent", intent=intent)
    return {"intent": intent}
