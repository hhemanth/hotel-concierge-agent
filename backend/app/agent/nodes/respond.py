"""Respond node: synthesise the final assistant message from state.

This is the only node that talks to the user. It branches on intent + booking
state and assembles an LLM prompt with the relevant context.

After generating the reply it also populates response_metadata so the SSE
transport (and frontend) can render property cards and surface booking results
without parsing the free-text reply.
"""

from __future__ import annotations

import json
import os

from anthropic import Anthropic

from app.agent.state import AgentState
from app.observability import logger, timed_llm_call

_SYSTEM_BASE = """You are a warm, helpful concierge for TFE Hotels (a hotel group operating Vibe, Adina, and Travelodge brands in Australia and New Zealand).

Voice:
- Friendly and direct. Short sentences.
- Use **bold** for hotel names, dates, and prices so they stand out.
- Use bullet points when listing amenities, policies, or multiple facts.
- Never invent facts. If the retrieved context doesn't cover the question, say so and offer to connect the guest to the property's front desk.

Formatting (markdown is rendered in the UI):
- Hotel names → **bold**
- Prices → **AUD 299/night**
- Dates → **15 Jun – 17 Jun**
- Key facts (check-in time, policy) → use a short bullet list

CRITICAL — you are the final step in the pipeline. All searches and availability checks have ALREADY run before you receive this prompt. Never say "let me check", "I'll look that up", "let me search", or any phrase that implies a future action. Results are either present in your context or absent. If nothing matched, say so directly and offer alternatives.

Demo disclosure: when asked, you may explain that this is a demo built on synthetic data, with a mocked booking back-end. Don't volunteer that unless asked."""


def _format_docs(docs: list[dict]) -> str:
    if not docs:
        return "(no relevant context found)"
    parts = []
    for d in docs:
        parts.append(f"[{d['source']} — {d['title']}]\n{d['text']}")
    return "\n\n".join(parts)


def _format_options(options: list[dict]) -> str:
    """Format available hotel options as a numbered list for the LLM prompt."""
    lines = []
    for i, o in enumerate(options, 1):
        name = o.get("name", o.get("property_id", f"Option {i}"))
        pid = o.get("property_id", "")
        neighbourhood = o.get("neighbourhood", "")
        price = o.get("price_per_night")
        amenities = o.get("amenities", [])
        offers = o.get("offers", [])

        line = f"{i}. {name}"
        if pid:
            line += f" ({pid})"
        if neighbourhood:
            line += f" — {neighbourhood}"
        if price is not None:
            line += f", AUD {price:.0f}/night"
        if amenities:
            line += f", amenities: {', '.join(amenities)}"
        if offers:
            offer_strs = [f"{of['name']} ({of['discount_pct']}% off)" for of in offers if "name" in of]
            if offer_strs:
                line += f", offers: {'; '.join(offer_strs)}"
        lines.append(line)
    return "\n".join(lines)


def _format_booking_result(result: dict) -> str:
    """Format a confirmed booking result for the LLM prompt."""
    return json.dumps(result, indent=2)


def _build_user_block(state: AgentState) -> str:  # noqa: C901
    intent = state.get("intent")
    messages = state.get("messages", [])
    latest = messages[-1]["content"] if messages else ""

    # Enhanced booking fields (Steps 7–10)
    available_options: list[dict] = state.get("available_options") or []
    booking_result: dict | None = state.get("booking_result")
    search_criteria: dict = state.get("search_criteria") or {}

    # ------------------------------------------------------------------
    # Info intent: RAG-backed Q&A
    # ------------------------------------------------------------------
    if intent == "info":
        docs = state.get("retrieved_docs") or []
        return (
            f"User question: {latest}\n\n"
            f"Retrieved context:\n{_format_docs(docs)}\n\n"
            "Answer the user's question using ONLY the retrieved context. "
            "If the context doesn't cover it, say so honestly."
        )

    # ------------------------------------------------------------------
    # Booking intent: multi-turn booking flow
    # ------------------------------------------------------------------
    if intent == "booking":
        booking: dict = state.get("booking_in_progress") or {}

        # 1. Confirmed booking result (from enhanced booking node)
        if booking_result and booking_result.get("booking_id"):
            return (
                f"Booking confirmed:\n{_format_booking_result(booking_result)}\n\n"
                "Confirm the booking warmly to the user. Include the booking id, "
                "property name, dates, and a one-line next-step (e.g. confirmation email)."
            )

        # 2. Legacy confirmed booking (from old booking flow)
        if booking.get("confirmed_booking_id"):
            return (
                f"Booking confirmed:\n{json.dumps(booking, indent=2)}\n\n"
                "Confirm the booking warmly to the user. Include the booking id, "
                "property name, dates, and a one-line next-step (e.g. confirmation email)."
            )

        # 3. Available options to present (from enhanced booking node)
        if available_options:
            mode = search_criteria.get("mode", "direct")
            if mode == "search":
                preamble = "Search results:"
            else:
                preamble = "Availability result:"
            return (
                f"User said: {latest}\n\n"
                f"Booking criteria: {json.dumps(booking, indent=2)}\n\n"
                f"{preamble}\n{_format_options(available_options)}\n\n"
                "Present these options to the user conversationally. "
                "Include price, location, amenities, and any applicable offers. "
                "Ask which they'd like to book or if they want to refine their criteria. "
                "Reference options by number (e.g. 'Option 1')."
            )

        # 4. Legacy candidate_options (from old booking flow)
        legacy_options: list[dict] = booking.get("candidate_options") or []
        if legacy_options:
            return (
                f"User said: {latest}\n\n"
                f"Booking criteria: {json.dumps(booking, indent=2)}\n\n"
                f"Available options:\n{_format_options(legacy_options)}\n\n"
                "Present these options to the user, conversationally. "
                "Ask which they'd like to book or if they want to refine."
            )

        # 5. Missing parameters: only applies to direct mode.
        # In search/browse mode the user doesn't need to specify every field up front.
        mode = search_criteria.get("mode", "direct")
        if mode == "direct":
            required = ("city", "check_in", "check_out", "guests")
            missing = [k for k in required if not booking.get(k)]
            if missing:
                return (
                    f"User said: {latest}\n\n"
                    f"Booking so far: {json.dumps(booking, indent=2)}\n\n"
                    f"You're missing: {', '.join(missing)}. "
                    "Ask the user a single friendly follow-up question to gather what's missing. "
                    "Do NOT say you will search or check availability — just ask for the missing detail."
                )

        # 6. No availability matched
        return (
            f"User said: {latest}\n\nBooking state: {json.dumps(booking, indent=2)}\n\n"
            "The availability search already ran and returned no matches. "
            "Tell the user directly that no availability was found for their request. "
            "Do NOT say you will check or look anything up. "
            "Suggest they try different dates, a different city, or ask about other TFE properties."
        )

    # ------------------------------------------------------------------
    # Smalltalk / unknown
    # ------------------------------------------------------------------
    return f"User said: {latest}\n\nReply warmly and briefly."


async def run(state: AgentState) -> dict:
    model = os.getenv("AGENT_MODEL", "claude-sonnet-4-6")
    user_block = _build_user_block(state)

    # Build multi-turn history so the LLM has conversational memory.
    # All prior turns are passed as-is; the current turn uses the enriched
    # user_block (injecting RAG context, booking options, etc.) instead of
    # the raw user message.
    raw_messages = state.get("messages") or []
    llm_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in raw_messages[:-1]  # everything except the latest user turn
    ]
    llm_messages.append({"role": "user", "content": user_block})

    with timed_llm_call(model=model, node="respond") as usage:
        resp = Anthropic().messages.create(
            model=model,
            max_tokens=600,
            system=_SYSTEM_BASE,
            messages=llm_messages,
        )
        usage["input_tokens"] = resp.usage.input_tokens
        usage["output_tokens"] = resp.usage.output_tokens

    reply = resp.content[0].text.strip() if resp.content else ""
    logger.info("respond", chars=len(reply))

    # Populate response_metadata for SSE transport and frontend card rendering
    response_metadata: dict = {
        "mentioned_properties": state.get("mentioned_properties") or [],
        "available_options": state.get("available_options") or [],
        "booking_result": state.get("booking_result"),
    }

    return {"response": reply, "response_metadata": response_metadata}
