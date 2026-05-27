"""TFE Booking MCP Server.

Exposes hotel search, availability, offers, and booking tools.
Run standalone: python -m app.mcp.booking_server
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import structlog
from fastmcp import FastMCP

from app.data.properties import load_properties
from app.tools.booking_api import (
    check_availability,
    cancel_booking,
    create_booking,
    get_booking,
)

logger = structlog.get_logger()

mcp = FastMCP("TFE Booking")

# ---------------------------------------------------------------------------
# Inventory data (used for price filtering in search_hotels)
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _load_inventory() -> list[dict]:
    path = _DATA_DIR / "inventory.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


_INVENTORY = _load_inventory()

# ---------------------------------------------------------------------------
# Offers catalogue (module-level constant)
# ---------------------------------------------------------------------------

OFFERS: list[dict] = [
    {"id": "weekend", "name": "Weekend Escape", "discount_pct": 10, "min_nights": 2, "weekend_only": True},
    {"id": "earlybird", "name": "Early Bird", "discount_pct": 15, "min_nights": 3},
    {"id": "extended", "name": "Extended Stay", "discount_pct": 20, "min_nights": 5},
]


# ---------------------------------------------------------------------------
# Helper: compute average inventory price for a property
# ---------------------------------------------------------------------------

def _avg_price_for_property(property_id: str) -> float | None:
    entries = [i for i in _INVENTORY if i["property_id"] == property_id]
    if not entries:
        return None
    return sum(e["price_aud"] for e in entries) / len(entries)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search_hotels(
    location: str | None = None,
    amenities: list[str] | None = None,
    vibe: list[str] | None = None,
    max_price_aud: float | None = None,
    min_nights: int | None = None,  # noqa: ARG001 — reserved for future use
) -> list[dict]:
    """Search TFE Hotels by location, amenities, vibe, and price.

    Args:
        location: City name (e.g. "Sydney", "Melbourne") or a location hint
                  such as a neighbourhood ("Surry Hills", "Bondi") or keyword
                  ("beach", "CBD", "waterfront").
        amenities: List of required amenities, e.g. ["gym", "pool", "parking"].
                   Each amenity is matched as a case-insensitive substring
                   against the property's amenity list.
        vibe: List of atmosphere keywords, e.g. ["romantic", "family", "beach"].
              Matched (case-insensitive substring) against description and amenities.
        max_price_aud: Maximum average nightly rate in AUD.
        min_nights: Minimum length of stay (currently informational; not used to
                    filter inventory — pass check_in/check_out to check_hotel_availability
                    for a hard availability check).

    Returns:
        Up to 10 matching property dicts (all fields from properties.json).
    """
    try:
        properties = load_properties()

        results: list[dict] = []
        for prop in properties:
            # Location filter: match city OR neighbourhood/description/amenities
            if location:
                loc = location.lower()
                city_match = prop.get("city", "").lower() == loc
                neighbourhood_match = loc in prop.get("neighbourhood", "").lower()
                description_match = loc in prop.get("description", "").lower()
                amenities_text = " ".join(prop.get("amenities", [])).lower()
                amenity_hint_match = loc in amenities_text
                if not (city_match or neighbourhood_match or description_match or amenity_hint_match):
                    continue

            # Amenities filter: every requested amenity must match at least one
            if amenities:
                prop_amenities_lower = [a.lower() for a in prop.get("amenities", [])]
                all_match = all(
                    any(req.lower() in prop_a for prop_a in prop_amenities_lower)
                    for req in amenities
                )
                if not all_match:
                    continue

            # Vibe filter: each vibe word must appear in description or amenities
            if vibe:
                combined_text = (
                    prop.get("description", "").lower()
                    + " "
                    + " ".join(prop.get("amenities", [])).lower()
                )
                if not all(v.lower() in combined_text for v in vibe):
                    continue

            # Price filter: use average inventory price for this property
            if max_price_aud is not None:
                avg_price = _avg_price_for_property(prop["property_id"])
                if avg_price is not None and avg_price > max_price_aud:
                    continue

            results.append(prop)

        return results[:10]

    except Exception as exc:
        logger.error("search_hotels_error", error=str(exc))
        return [{"error": str(exc)}]


@mcp.tool()
def check_hotel_availability(
    property_id: str,
    check_in: str,
    check_out: str,
    guests: int,
) -> dict:
    """Check room availability for a specific TFE property and date range.

    Args:
        property_id: The property identifier, e.g. "vibe-sydney".
        check_in: ISO date string "YYYY-MM-DD".
        check_out: ISO date string "YYYY-MM-DD".
        guests: Number of guests.

    Returns:
        Dict with keys:
          - available (bool)
          - property (dict | None): PropertyOption if available, else None
          - nightly_rate (float | None): Average nightly rate if available
    """
    try:
        # Resolve property to get city
        properties = load_properties()
        prop = next((p for p in properties if p["property_id"] == property_id), None)
        if prop is None:
            return {"available": False, "property": None, "nightly_rate": None,
                    "error": f"Unknown property_id: {property_id}"}

        city = prop["city"]

        # check_availability filters by city; filter down to specific property_id
        options = check_availability(
            city=city,
            check_in=check_in,
            check_out=check_out,
            guests=guests,
        )
        matched = next((o for o in options if o["property_id"] == property_id), None)

        if matched is None:
            return {"available": False, "property": None, "nightly_rate": None}

        return {
            "available": True,
            "property": matched,
            "nightly_rate": matched["price_per_night"],
        }

    except Exception as exc:
        logger.error("check_hotel_availability_error", property_id=property_id, error=str(exc))
        return {"available": False, "property": None, "nightly_rate": None, "error": str(exc)}


@mcp.tool()
def get_hotel_offers(property_id: str, nights: int) -> list[dict]:
    """Return applicable discount offers for a TFE property given the length of stay.

    Weekend-only offers apply only when today is Friday, Saturday, or Sunday.

    Args:
        property_id: The property identifier (currently informational; offers are
                     property-agnostic in this demo).
        nights: Number of nights for the stay.

    Returns:
        List of applicable offer dicts, each with keys: id, name, discount_pct.
    """
    try:
        today_weekday = date.today().weekday()  # Mon=0 … Sun=6
        is_weekend = today_weekday in (4, 5, 6)  # Fri, Sat, Sun

        applicable: list[dict] = []
        for offer in OFFERS:
            if nights < offer.get("min_nights", 1):
                continue
            if offer.get("weekend_only") and not is_weekend:
                continue
            applicable.append({
                "id": offer["id"],
                "name": offer["name"],
                "discount_pct": offer["discount_pct"],
            })

        logger.info(
            "get_hotel_offers",
            property_id=property_id,
            nights=nights,
            n_offers=len(applicable),
        )
        return applicable

    except Exception as exc:
        logger.error("get_hotel_offers_error", property_id=property_id, error=str(exc))
        return [{"error": str(exc)}]


@mcp.tool()
def create_hotel_booking(
    property_id: str,
    check_in: str,
    check_out: str,
    guests: int,
    offer_id: str | None = None,
) -> dict:
    """Create a confirmed hotel booking.

    Args:
        property_id: The property identifier.
        check_in: ISO date "YYYY-MM-DD".
        check_out: ISO date "YYYY-MM-DD".
        guests: Number of guests.
        offer_id: Optional offer id from get_hotel_offers to apply a discount.

    Returns:
        Booking confirmation dict including booking_id, total_aud, status, and
        offer_applied (dict | None).
    """
    try:
        confirmation = create_booking(
            property_id=property_id,
            check_in=check_in,
            check_out=check_out,
            guests=guests,
        )

        # Apply discount if offer_id provided
        offer_applied: dict | None = None
        if offer_id:
            offer = next((o for o in OFFERS if o["id"] == offer_id), None)
            if offer:
                discount_factor = 1 - (offer["discount_pct"] / 100)
                confirmation["total_aud"] = round(confirmation["total_aud"] * discount_factor, 2)
                offer_applied = {
                    "id": offer["id"],
                    "name": offer["name"],
                    "discount_pct": offer["discount_pct"],
                }
            else:
                logger.warning("create_hotel_booking_unknown_offer", offer_id=offer_id)

        result = dict(confirmation)
        result["offer_applied"] = offer_applied

        logger.info(
            "create_hotel_booking",
            booking_id=result["booking_id"],
            property_id=property_id,
            total_aud=result["total_aud"],
            offer_applied=offer_applied,
        )
        return result

    except Exception as exc:
        logger.error("create_hotel_booking_error", property_id=property_id, error=str(exc))
        return {"error": str(exc)}


@mcp.tool()
def cancel_hotel_booking(booking_id: str) -> dict:
    """Cancel an existing TFE hotel booking.

    Args:
        booking_id: The booking identifier (e.g. "BK-A1B2C3D4").

    Returns:
        Dict with booking_id and status "cancelled", or an error dict.
    """
    try:
        result = cancel_booking(booking_id)
        logger.info("cancel_hotel_booking", booking_id=booking_id)
        return result
    except Exception as exc:
        logger.error("cancel_hotel_booking_error", booking_id=booking_id, error=str(exc))
        return {"error": str(exc)}


@mcp.tool()
def get_hotel_booking(booking_id: str) -> dict:
    """Retrieve the details of an existing TFE hotel booking.

    Args:
        booking_id: The booking identifier.

    Returns:
        Booking confirmation dict, or {"found": False} if not found.
    """
    try:
        booking = get_booking(booking_id)
        if booking is None:
            return {"found": False}
        return dict(booking)
    except Exception as exc:
        logger.error("get_hotel_booking_error", booking_id=booking_id, error=str(exc))
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()  # stdio transport (default for fastmcp)
