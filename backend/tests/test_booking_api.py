"""Unit tests for the pure mock booking API."""

from app.tools.booking_api import check_availability, create_booking


def test_check_availability_returns_city_matches():
    options = check_availability(
        city="sydney", check_in="2026-07-10", check_out="2026-07-12", guests=2
    )
    assert options, "expected at least one Sydney property"
    assert all(o["city"].lower() == "sydney" for o in options)


def test_check_availability_respects_price_cap():
    capped = check_availability(
        city="sydney",
        check_in="2026-07-10",
        check_out="2026-07-12",
        guests=2,
        max_price_per_night=250,
    )
    assert all(o["price_per_night"] <= 250 for o in capped)


def test_create_booking_returns_confirmation():
    result = create_booking(
        property_id="vibe-sydney",
        check_in="2026-07-10",
        check_out="2026-07-12",
        guests=2,
    )
    assert result["booking_id"].startswith("BK-")
    assert result["status"] == "confirmed"
    assert result["total_aud"] > 0
