"""Booking node: take a complete BookingState and progress the flow.

Flow:
    1. If no candidate_options yet → call check_availability, store options.
    2. Else if user picked an option → call create_booking, store confirmation.
    3. Else → keep candidate_options; the respond node will present them.

The "user picked an option" signal is sniffed from the latest user message
(look for a property id or 'book it' / 'go with X').

STUB — implement step 2 (selection sniff + confirm) once you have time.
"""

from __future__ import annotations

import re

from app.agent.state import AgentState, BookingState
from app.observability import logger
from app.tools.booking_api import check_availability, create_booking


def _detect_selection(latest_user_msg: str, options: list[dict]) -> str | None:
    """Look for a property id or close name match in the user's message."""
    msg = latest_user_msg.lower()
    for opt in options:
        pid = opt["property_id"].lower()
        name = opt["name"].lower()
        if pid in msg or name in msg:
            return opt["property_id"]
    # Crude fallback: "option 1", "the first one"
    if re.search(r"\b(first|1st|one)\b", msg) and options:
        return options[0]["property_id"]
    if re.search(r"\b(second|2nd|two)\b", msg) and len(options) > 1:
        return options[1]["property_id"]
    return None


async def run(state: AgentState) -> dict:
    booking: BookingState = state.get("booking_in_progress") or {}  # type: ignore[assignment]
    messages = state.get("messages", [])
    latest = messages[-1]["content"] if messages else ""

    # If we don't have candidates yet, fetch them.
    if not booking.get("candidate_options"):
        options = check_availability(
            city=booking["city"],
            check_in=booking["check_in"],
            check_out=booking["check_out"],
            guests=booking["guests"],
            max_price_per_night=booking.get("max_price_per_night"),
            preferences=booking.get("preferences", []),
        )
        booking["candidate_options"] = options
        logger.info("availability", n=len(options))
        return {"booking_in_progress": booking}

    # If user is selecting one, confirm.
    selected_id = _detect_selection(latest, booking["candidate_options"])
    if selected_id:
        confirmation = create_booking(
            property_id=selected_id,
            check_in=booking["check_in"],
            check_out=booking["check_out"],
            guests=booking["guests"],
        )
        booking["selected_option_id"] = selected_id
        booking["confirmed_booking_id"] = confirmation["booking_id"]
        logger.info("booking_confirmed", booking_id=confirmation["booking_id"])
        return {"booking_in_progress": booking}

    # Otherwise hold state and let respond ask the user to pick.
    return {"booking_in_progress": booking}
