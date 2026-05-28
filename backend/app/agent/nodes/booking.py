"""Booking node: progress the booking flow using MCP tool functions.

Flow:
    1. If selected_option is set and available_options exist → confirm booking.
    2. If mode == "search" → search_hotels + get_hotel_offers for top results.
    3. If mode == "direct" → check_hotel_availability + get_hotel_offers for
       the specific property.
    4. Fallback → hold state; respond node will ask for more info.

Tool functions are imported directly from app.mcp.booking_server.  The MCP
server architecture is demonstrated by booking_server.py existing as a
standalone FastMCP server; calling its pure functions directly is the right
pattern for an in-process agent (no subprocess overhead for a demo).
"""

from __future__ import annotations

from datetime import date

from app.agent.state import AgentState
from app.data.properties import load_properties
from app.mcp.booking_server import (
    check_hotel_availability,
    create_hotel_booking,
    get_hotel_offers,
    search_hotels,
)
from app.observability import logger

# ---------------------------------------------------------------------------
# Prompts / constants
# ---------------------------------------------------------------------------

_MIN_NIGHTS_DEFAULT = 2


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


async def run(state: AgentState) -> dict:  # noqa: C901
    """Advance the booking flow one step and return state delta."""

    search_criteria: dict = state.get("search_criteria") or {}
    mode: str = search_criteria.get("mode", "direct")
    selected_option: int | None = state.get("selected_option")
    available_options: list[dict] = state.get("available_options") or []
    booking_in_progress: dict = state.get("booking_in_progress") or {}

    # ------------------------------------------------------------------
    # Branch 1: user has selected an option → confirm booking
    # ------------------------------------------------------------------
    if selected_option is not None and available_options:
        idx = selected_option - 1  # convert 1-indexed to 0-indexed
        if 0 <= idx < len(available_options):
            chosen = available_options[idx]
            check_in = booking_in_progress.get("check_in") or chosen.get("check_in")
            check_out = booking_in_progress.get("check_out") or chosen.get("check_out")
            guests = booking_in_progress.get("guests") or chosen.get("guests", 1)
            property_id = chosen.get("property_id")

            if property_id and check_in and check_out and guests:
                result = create_hotel_booking(
                    property_id=property_id,
                    check_in=check_in,
                    check_out=check_out,
                    guests=int(guests),
                )
                logger.info(
                    "booking_confirmed",
                    property_id=property_id,
                    booking_id=result.get("booking_id"),
                )
                return {"booking_result": result}

        logger.warning("booking_selection_out_of_range", selected_option=selected_option)
        return {}

    # ------------------------------------------------------------------
    # Branch 2: search mode — find matching hotels
    # ------------------------------------------------------------------
    if mode == "search":
        location_hints: list[str] = search_criteria.get("location_hints") or []
        location = location_hints[0] if location_hints else None
        vibe_hints: list[str] = search_criteria.get("vibe_hints") or []
        min_nights: int | None = search_criteria.get("min_nights")

        vibe = vibe_hints[0] if vibe_hints else None
        amenities_param = booking_in_progress.get("preferences") or None
        max_price = booking_in_progress.get("max_price_per_night")
        options = search_hotels(
            location=location,
            amenities=amenities_param,
            vibe=vibe,
            max_price_aud=max_price,
            min_nights=min_nights,
        )
        # If the price cap produced no results, relax it and show closest options.
        if not options and max_price is not None:
            logger.info("search_mode_price_fallback", max_price=max_price)
            options = search_hotels(
                location=location,
                amenities=amenities_param,
                vibe=vibe,
                max_price_aud=None,
                min_nights=min_nights,
            )

        enriched: list[dict] = []
        for prop in options[:3]:
            nights = min_nights or _MIN_NIGHTS_DEFAULT
            offers = get_hotel_offers(property_id=prop["property_id"], nights=nights)
            enriched_prop = dict(prop)
            enriched_prop["offers"] = offers
            enriched.append(enriched_prop)

        mentioned = [p["property_id"] for p in enriched]
        logger.info("search_mode_results", n=len(enriched), mentioned=mentioned)
        return {"available_options": enriched, "mentioned_properties": mentioned}

    # ------------------------------------------------------------------
    # Branch 3: direct mode — check a specific property
    # ------------------------------------------------------------------
    if mode == "direct":
        check_in: str | None = booking_in_progress.get("check_in")
        check_out: str | None = booking_in_progress.get("check_out")
        guests_raw = booking_in_progress.get("guests")
        guests: int | None = int(guests_raw) if guests_raw is not None else None
        property_name: str | None = search_criteria.get("property_name")

        # Resolve property_id from name if given
        property_id: str | None = None
        if property_name:
            props = load_properties()
            for p in props:
                if property_name.lower() in p["name"].lower():
                    property_id = p["property_id"]
                    break

        if property_name and property_id is None:
            # Named property not found in the system — signal no match immediately
            logger.info("direct_mode_property_not_found", property_name=property_name)
            return {"available_options": []}

        if property_id and check_in and check_out and guests is not None:
            result = check_hotel_availability(
                property_id=property_id,
                check_in=check_in,
                check_out=check_out,
                guests=guests,
            )
            if result.get("available"):
                nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
                offers = get_hotel_offers(property_id=property_id, nights=nights)
                prop_data = result.get("property") or {}
                option = {
                    **prop_data,
                    "check_in": check_in,
                    "check_out": check_out,
                    "guests": guests,
                    "offers": offers,
                }
                logger.info("direct_mode_available", property_id=property_id, nights=nights)
                return {
                    "available_options": [option],
                    "mentioned_properties": [property_id],
                }
            else:
                logger.info("direct_mode_unavailable", property_id=property_id)
                return {"available_options": []}

    # ------------------------------------------------------------------
    # Fallback: incomplete params — hold state, let respond ask for more
    # ------------------------------------------------------------------
    logger.info("booking_node_fallback", mode=mode)
    return {}
