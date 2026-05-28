"""Shared state for the LangGraph agent.

All nodes read from and write to this TypedDict. Keep new fields additive —
existing nodes ignore unknown keys.
"""

from __future__ import annotations

from typing import Literal, TypedDict

Intent = Literal["info", "booking", "smalltalk", "unknown"]


class BookingState(TypedDict, total=False):
    """Per-session booking-in-progress state.

    Lives on the AgentState. Persists across turns (the frontend sends the
    full history; for richer persistence wire a Redis/Postgres store here).
    """
    city: str | None
    check_in: str | None       # ISO date
    check_out: str | None      # ISO date
    guests: int | None
    max_price_per_night: float | None
    preferences: list[str]     # e.g. ["near beach", "gym"]
    candidate_options: list[dict]
    selected_option_id: str | None
    confirmed_booking_id: str | None
    # A property the user picked from search results but for which we still
    # need dates/guests before we can book it (carried across turns).
    selected_property_id: str | None
    selected_property_name: str | None


class RetrievedDoc(TypedDict):
    id: str
    source: str            # "property:vibe-sydney", "faq:checkin", etc.
    title: str
    text: str
    score: float


class AgentState(TypedDict, total=False):
    """Graph state. `total=False` so each node only sets what it owns."""
    messages: list[dict]                 # [{role, content}, ...]
    session_id: str
    intent: Intent | None
    retrieved_docs: list[RetrievedDoc]
    booking_in_progress: BookingState | None
    response: str | None

    # Enhanced booking flow fields (Steps 7+8)
    search_criteria: dict | None         # vague search params (search mode)
    available_options: list[dict]        # hotels presented to user
    selected_option: int | None          # user's selection (1-indexed)
    booking_result: dict | None          # confirmed booking from create_hotel_booking
    mentioned_properties: list[str]      # property_ids for frontend card rendering
    response_metadata: dict | None       # populated by respond node for SSE metadata event
