"""Mock booking API.

Shaped like a real PMS/booking integration: stateless functions, JSON-y
inputs and outputs. Replace with real HTTP calls to the actual booking
provider once available — the agent code calling these will not change.

Storage is in-memory; restart wipes bookings. That's fine for a demo.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import NotRequired, TypedDict

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class PropertyOption(TypedDict):
    property_id: str
    name: str
    city: str
    neighbourhood: str
    price_per_night: float
    amenities: list[str]
    rating: float
    image_url: NotRequired[str]


class BookingConfirmation(TypedDict):
    booking_id: str
    property_id: str
    check_in: str
    check_out: str
    guests: int
    status: str
    total_aud: float


# ---------------------------------------------------------------------------
# Data load (sync at module import — small files)
# ---------------------------------------------------------------------------

def _load_json(name: str) -> list[dict]:
    path = _DATA_DIR / name
    if not path.exists():
        return []
    return json.loads(path.read_text())


_PROPERTIES = _load_json("properties.json")
_INVENTORY = _load_json("inventory.json")  # list of {property_id, date, available, price_aud}
_BOOKINGS: dict[str, BookingConfirmation] = {}

# Pre-compute per-property average price for use when a date has no inventory entry.
_DEFAULT_PRICE: dict[str, float] = {}
for _pid in {e["property_id"] for e in _INVENTORY}:
    _prices = [e["price_aud"] for e in _INVENTORY if e["property_id"] == _pid]
    _DEFAULT_PRICE[_pid] = round(sum(_prices) / len(_prices), 2) if _prices else 300.0


def _night_price(property_id: str, night: str) -> float:
    """Return the inventory price for a single night, or the property default."""
    entry = next(
        (i for i in _INVENTORY if i["property_id"] == property_id and i["date"] == night),
        None,
    )
    return entry["price_aud"] if entry else _DEFAULT_PRICE.get(property_id, 300.0)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _date_range(check_in: str, check_out: str) -> list[str]:
    start = date.fromisoformat(check_in)
    end = date.fromisoformat(check_out)
    days = (end - start).days
    return [(start.fromordinal(start.toordinal() + i)).isoformat() for i in range(days)]


def check_availability(
    *,
    city: str,
    check_in: str,
    check_out: str,
    guests: int,
    max_price_per_night: float | None = None,
    preferences: list[str] | None = None,
) -> list[PropertyOption]:
    """Return properties that match the criteria across all requested nights.

    Each returned option is averaged across nights for price_per_night.
    """
    preferences = preferences or []
    nights = _date_range(check_in, check_out)
    if not nights:
        return []

    # Filter properties by city + capacity
    candidates = [
        p for p in _PROPERTIES
        if p["city"].lower() == city.lower() and p.get("max_guests", 2) >= guests
    ]

    options: list[PropertyOption] = []
    for prop in candidates:
        pid = prop["property_id"]
        avg_price = sum(_night_price(pid, n) for n in nights) / len(nights)

        if max_price_per_night is not None and avg_price > max_price_per_night:
            continue

        # Preference soft-match: only include if all preferences match an amenity
        # (case-insensitive substring). This is intentionally simple — refine later.
        if preferences:
            amen = {a.lower() for a in prop.get("amenities", [])}
            wanted = {p.lower() for p in preferences}
            if not all(any(w in a for a in amen) for w in wanted):
                continue

        entry: PropertyOption = {
            "property_id": pid,
            "name": prop["name"],
            "city": prop["city"],
            "neighbourhood": prop.get("neighbourhood", ""),
            "price_per_night": round(avg_price, 2),
            "amenities": prop.get("amenities", []),
            "rating": prop.get("rating", 0.0),
        }
        if prop.get("image_url"):
            entry["image_url"] = prop["image_url"]
        options.append(entry)

    # Cheapest first
    options.sort(key=lambda o: o["price_per_night"])
    return options[:5]


def create_booking(
    *, property_id: str, check_in: str, check_out: str, guests: int
) -> BookingConfirmation:
    """Confirm a booking. Idempotency: callers should pass a stable session_id
    upstream — here we return a fresh booking_id each call (mock behaviour).
    """
    nights = _date_range(check_in, check_out)
    total = sum(_night_price(property_id, n) for n in nights)

    booking_id = f"BK-{uuid.uuid4().hex[:8].upper()}"
    confirmation: BookingConfirmation = {
        "booking_id": booking_id,
        "property_id": property_id,
        "check_in": check_in,
        "check_out": check_out,
        "guests": guests,
        "status": "confirmed",
        "total_aud": round(total, 2),
    }
    _BOOKINGS[booking_id] = confirmation
    return confirmation


def cancel_booking(booking_id: str) -> dict:
    if booking_id not in _BOOKINGS:
        raise ValueError(f"Unknown booking_id: {booking_id}")
    _BOOKINGS[booking_id]["status"] = "cancelled"
    return {"booking_id": booking_id, "status": "cancelled"}


def get_booking(booking_id: str) -> BookingConfirmation | None:
    return _BOOKINGS.get(booking_id)
