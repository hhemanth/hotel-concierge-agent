"""Respond node: synthesise the final assistant message from state.

This is the only node that talks to the user. It branches on intent + booking
state and assembles an LLM prompt with the relevant context.
"""

from __future__ import annotations

import os

from anthropic import Anthropic

from app.agent.state import AgentState
from app.observability import logger, timed_llm_call


_SYSTEM_BASE = """You are a warm, helpful concierge for TFE Hotels (a hotel group operating Vibe, Adina, and Travelodge brands in Australia and New Zealand).

Voice:
- Friendly and direct. Short sentences.
- Use bullet points sparingly — only when listing 3+ options.
- Never invent facts. If the retrieved context doesn't cover the question, say so and offer to connect the guest to the property's front desk.

Demo disclosure: when asked, you may explain that this is a demo built on synthetic data, with a mocked booking back-end. Don't volunteer that unless asked."""


def _format_docs(docs: list[dict]) -> str:
    if not docs:
        return "(no relevant context found)"
    parts = []
    for d in docs:
        parts.append(f"[{d['source']} — {d['title']}]\n{d['text']}")
    return "\n\n".join(parts)


def _format_options(options: list[dict]) -> str:
    lines = []
    for i, o in enumerate(options, 1):
        lines.append(
            f"{i}. {o['name']} ({o['property_id']}) — {o['neighbourhood']}, "
            f"AUD {o['price_per_night']:.0f}/night, "
            f"amenities: {', '.join(o.get('amenities', []))}."
        )
    return "\n".join(lines)


def _build_user_block(state: AgentState) -> str:
    intent = state.get("intent")
    messages = state.get("messages", [])
    latest = messages[-1]["content"] if messages else ""

    if intent == "info":
        docs = state.get("retrieved_docs") or []
        return (
            f"User question: {latest}\n\n"
            f"Retrieved context:\n{_format_docs(docs)}\n\n"
            "Answer the user's question using ONLY the retrieved context. "
            "If the context doesn't cover it, say so honestly."
        )

    if intent == "booking":
        booking = state.get("booking_in_progress") or {}
        required = ("city", "check_in", "check_out", "guests")
        missing = [k for k in required if not booking.get(k)]
        if missing:
            return (
                f"User said: {latest}\n\n"
                f"Booking so far: {booking}\n\n"
                f"You're missing: {', '.join(missing)}. "
                "Ask the user a single friendly follow-up question that gathers "
                "what's missing. Don't dump every field at once — pick the most natural."
            )
        if booking.get("confirmed_booking_id"):
            return (
                f"Booking confirmed:\n{booking}\n\n"
                "Confirm the booking warmly to the user. Include the booking id, "
                "property name, dates, and a one-line next-step (e.g. confirmation email)."
            )
        options = booking.get("candidate_options") or []
        if options:
            return (
                f"User said: {latest}\n\n"
                f"Booking criteria: {booking}\n\n"
                f"Available options:\n{_format_options(options)}\n\n"
                "Present these options to the user, conversationally. "
                "Ask which they'd like to book or if they want to refine."
            )
        return (
            f"User said: {latest}\n\nBooking state: {booking}\n\n"
            "No availability matched. Apologise, suggest the closest near-misses, "
            "and offer to adjust dates or budget."
        )

    # smalltalk / unknown
    return f"User said: {latest}\n\nReply warmly and briefly."


async def run(state: AgentState) -> dict:
    model = os.getenv("AGENT_MODEL", "claude-sonnet-4-6")
    user_block = _build_user_block(state)

    with timed_llm_call(model=model, node="respond") as usage:
        resp = Anthropic().messages.create(
            model=model,
            max_tokens=600,
            system=_SYSTEM_BASE,
            messages=[{"role": "user", "content": user_block}],
        )
        usage["input_tokens"] = resp.usage.input_tokens
        usage["output_tokens"] = resp.usage.output_tokens

    reply = resp.content[0].text.strip() if resp.content else ""
    logger.info("respond", chars=len(reply))
    return {"response": reply}
