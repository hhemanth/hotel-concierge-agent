"""TFE Hotels public website scraper.

Scrapes publicly available hotel data from tfehotels.com and writes
``properties_scraped.json`` in the same directory.  The scraper is
best-effort: individual page failures are logged and skipped; if the
entire run fails the output file is written with an empty list so
downstream code never crashes.

Data source: TFE Hotels public website (tfehotels.com)
Honesty note: Data scraped from public pages; may not reflect current
listings. This is NOT TFE's real production system — it is a portfolio demo.

Usage:
    cd backend
    python -m app.data.scrape_tfe
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.robotparser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from app.observability import logger

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.tfehotels.com"
HOTELS_PATH = "/en/hotels/"
USER_AGENT = "TFE-Portfolio-Demo/1.0"
MAX_HOTELS = 20
REQUEST_DELAY = 0.5  # seconds between page requests
OUTPUT_PATH = Path(__file__).parent / "properties_scraped.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert a hotel name to a URL-friendly property_id slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def _text(tag: Any) -> str | None:
    """Safely extract stripped text from a BeautifulSoup tag or None."""
    if tag is None:
        return None
    return tag.get_text(separator=" ", strip=True) or None


def _first(*args: Any) -> Any:
    """Return the first truthy value from a sequence."""
    for v in args:
        if v:
            return v
    return None


def _check_robots(base_url: str) -> urllib.robotparser.RobotFileParser:
    """Fetch and parse robots.txt synchronously (called once before scraping)."""
    rp = urllib.robotparser.RobotFileParser()
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        rp.set_url(robots_url)
        rp.read()
        logger.info("robots_txt_loaded", url=robots_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("robots_txt_failed", url=robots_url, error=str(exc))
        # Permissive default: allow everything if robots.txt is unreachable
        rp.allow_all = True  # type: ignore[attr-defined]
    return rp


def _can_fetch(rp: urllib.robotparser.RobotFileParser, url: str) -> bool:
    """Return True if robots.txt allows us to fetch this URL."""
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:  # noqa: BLE001
        return True  # permissive default


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------


def _extract_description(soup: BeautifulSoup) -> str:
    """Try several selectors for the hotel's main description text."""
    tag = _first(
        soup.select_one(".hotel-description"),
        soup.select_one(".property-description"),
        soup.select_one("[class*='description']"),
        soup.select_one(".about-hotel"),
        soup.select_one("[class*='intro']"),
        soup.select_one("meta[name='description']"),
    )
    if tag is None:
        return ""
    # <meta> tags expose content via .get(), not text
    if tag.name == "meta":
        return tag.get("content", "") or ""
    return _text(tag) or ""


def _extract_amenities(soup: BeautifulSoup) -> list[str]:
    """Extract a list of amenity strings from the page."""
    # Try structured amenity lists first
    for selector in (
        ".amenities-list li",
        ".hotel-amenities li",
        "[class*='amenity'] li",
        "[class*='facilities'] li",
        ".features li",
    ):
        items = soup.select(selector)
        if items:
            return [_text(i) for i in items if _text(i)]

    # Fallback: look for an amenities section heading and grab nearby list
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if heading.get_text(strip=True).lower() in {"amenities", "facilities", "features"}:
            sibling_list = heading.find_next_sibling("ul")
            if sibling_list:
                items = sibling_list.find_all("li")
                return [_text(i) for i in items if _text(i)]

    return []


def _extract_check_times(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (check_in_time, check_out_time) in HH:MM format or defaults."""
    check_in = "14:00"
    check_out = "11:00"

    page_text = soup.get_text(separator=" ")
    # Match patterns like "Check-in: 2:00 PM" / "check in from 14:00" etc.
    ci_match = re.search(
        r"check[\s\-]?in[:\s]+(?:from\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        page_text,
        re.IGNORECASE,
    )
    co_match = re.search(
        r"check[\s\-]?out[:\s]+(?:by\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        page_text,
        re.IGNORECASE,
    )

    def _to_24h(raw: str) -> str:
        raw = raw.strip().lower()
        # Already 24h with colon, e.g. "14:00"
        if re.match(r"^\d{2}:\d{2}$", raw):
            return raw
        # 12h format
        ampm_match = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", raw)
        if ampm_match:
            hour = int(ampm_match.group(1))
            minute = int(ampm_match.group(2) or 0)
            if ampm_match.group(3) == "pm" and hour != 12:
                hour += 12
            elif ampm_match.group(3) == "am" and hour == 12:
                hour = 0
            return f"{hour:02d}:{minute:02d}"
        # Bare number like "14"
        bare = re.match(r"^(\d{1,2})$", raw)
        if bare:
            return f"{int(bare.group(1)):02d}:00"
        return raw  # give up, return as-is

    if ci_match:
        check_in = _to_24h(ci_match.group(1))
    if co_match:
        check_out = _to_24h(co_match.group(1))

    return check_in, check_out


def _extract_pet_policy(soup: BeautifulSoup) -> str:
    """Return a short pet-policy string."""
    page_text = soup.get_text(separator=" ")
    if re.search(r"\bpet[\s\-]?friendly\b", page_text, re.IGNORECASE):
        return "Pets welcome"
    if re.search(r"\bpets?\s+(are\s+)?(?:not\s+)?(?:permitted|allowed|accepted)\b",
                 page_text, re.IGNORECASE):
        match = re.search(
            r"pets?\s+(?:are\s+)?(?:not\s+)?(?:permitted|allowed|accepted)[^.]*\.",
            page_text,
            re.IGNORECASE,
        )
        if match:
            return match.group(0).strip()
    # No mention — conservatively say not permitted
    return "Pets not permitted"


def _extract_parking(soup: BeautifulSoup) -> str:
    """Return a short parking-policy string."""
    page_text = soup.get_text(separator=" ")
    parking_match = re.search(
        r"parking[^.]{0,120}\.",
        page_text,
        re.IGNORECASE,
    )
    if parking_match:
        snippet = parking_match.group(0).strip()
        # Truncate if excessively long
        return snippet if len(snippet) <= 120 else snippet[:117] + "..."
    return "Parking information not available"


def _extract_address(soup: BeautifulSoup) -> str:
    """Extract a hotel address."""
    tag = _first(
        soup.select_one("[itemprop='streetAddress']"),
        soup.select_one(".hotel-address"),
        soup.select_one("[class*='address']"),
        soup.select_one("address"),
    )
    return _text(tag) or ""


def _extract_rating(soup: BeautifulSoup) -> float | None:
    """Extract a numeric star/guest rating if present."""
    # Try schema.org markup first
    tag = _first(
        soup.select_one("[itemprop='ratingValue']"),
        soup.select_one(".star-rating"),
        soup.select_one("[class*='rating']"),
    )
    if tag:
        raw = (tag.get("content") or _text(tag) or "").strip()
        match = re.search(r"(\d+(?:\.\d+)?)", raw)
        if match:
            try:
                val = float(match.group(1))
                # Ratings are typically 1–5; ignore values like year numbers
                if 1.0 <= val <= 5.0:
                    return round(val, 1)
            except ValueError:
                pass
    return None


def _extract_city_neighbourhood(soup: BeautifulSoup, name: str) -> tuple[str, str]:
    """Infer city and neighbourhood from page content or hotel name."""
    # Try meta / structured data
    city_tag = _first(
        soup.select_one("[itemprop='addressLocality']"),
        soup.select_one("[class*='city']"),
        soup.select_one("[class*='location']"),
    )
    city = _text(city_tag) or ""

    neighbourhood_tag = _first(
        soup.select_one("[itemprop='addressRegion']"),
        soup.select_one("[class*='neighbourhood']"),
        soup.select_one("[class*='suburb']"),
        soup.select_one("[class*='area']"),
    )
    neighbourhood = _text(neighbourhood_tag) or ""

    # Heuristic: well-known cities in TFE's portfolio
    known_cities = [
        "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide",
        "Canberra", "Auckland", "Wellington", "Queenstown",
    ]
    if not city:
        for kc in known_cities:
            if kc.lower() in name.lower():
                city = kc
                break

    return city.lower(), neighbourhood


# ---------------------------------------------------------------------------
# Page-level scraping
# ---------------------------------------------------------------------------


async def _get_hotel_urls(
    client: httpx.AsyncClient,
    rp: urllib.robotparser.RobotFileParser,
) -> list[str]:
    """Fetch the hotels listing page and return absolute URLs to detail pages."""
    listing_url = urljoin(BASE_URL, HOTELS_PATH)

    if not _can_fetch(rp, listing_url):
        logger.warning("robots_disallowed", url=listing_url)
        return []

    try:
        resp = await client.get(listing_url)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("listing_page_failed", url=listing_url, error=str(exc))
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    urls: list[str] = []
    # Look for links that plausibly point to individual hotel pages
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        # Heuristic: hotel detail paths often contain /hotels/ + a slug
        if "/hotels/" in href and href.rstrip("/") != HOTELS_PATH.rstrip("/"):
            abs_url = urljoin(BASE_URL, href)
            # De-duplicate and keep same domain only
            if abs_url not in urls and urlparse(abs_url).netloc == urlparse(BASE_URL).netloc:
                urls.append(abs_url)

    logger.info("hotel_urls_found", count=len(urls))
    return urls[:MAX_HOTELS]


async def _scrape_hotel_page(
    client: httpx.AsyncClient,
    url: str,
    rp: urllib.robotparser.RobotFileParser,
) -> dict | None:
    """Scrape a single hotel detail page and return a property dict or None."""
    if not _can_fetch(rp, url):
        logger.warning("robots_disallowed", url=url)
        return None

    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("hotel_page_failed", url=url, error=str(exc))
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # --- Name ---
    name_tag = _first(
        soup.select_one("h1"),
        soup.select_one("[itemprop='name']"),
        soup.select_one(".hotel-name"),
        soup.select_one("[class*='hotel-title']"),
    )
    name = _text(name_tag) or ""
    if not name:
        logger.warning("hotel_name_missing", url=url)
        return None

    city, neighbourhood = _extract_city_neighbourhood(soup, name)
    check_in, check_out = _extract_check_times(soup)

    property_dict: dict = {
        "property_id": _slugify(name),
        "name": name,
        "city": city,
        "neighbourhood": neighbourhood,
        "max_guests": 4,  # default; TFE site rarely surfaces this
        "rating": _extract_rating(soup),
        "amenities": _extract_amenities(soup),
        "description": _extract_description(soup),
        "check_in_time": check_in,
        "check_out_time": check_out,
        "pet_policy": _extract_pet_policy(soup),
        "parking": _extract_parking(soup),
        "address": _extract_address(soup),
    }

    logger.info("hotel_scraped", name=name, city=city)
    return property_dict


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the scraper and write properties_scraped.json."""
    properties: list[dict] = []

    try:
        # 1. Check robots.txt (synchronous — called once)
        rp = _check_robots(BASE_URL)

        # 2. Build HTTP client with portfolio user-agent
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=15.0,
        ) as client:
            # 3. Discover hotel URLs from the listing page
            hotel_urls = await _get_hotel_urls(client, rp)

            if not hotel_urls:
                logger.warning("no_hotel_urls_found", base=BASE_URL)

            # 4. Scrape each hotel page with a polite delay
            for url in hotel_urls:
                result = await _scrape_hotel_page(client, url, rp)
                if result is not None:
                    properties.append(result)
                await asyncio.sleep(REQUEST_DELAY)

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scraper_failed",
            error=str(exc),
            hotels_collected=len(properties),
        )

    # Always write output, even on total failure
    OUTPUT_PATH.write_text(json.dumps(properties, indent=2, ensure_ascii=False))
    logger.info(
        "scrape_complete",
        output=str(OUTPUT_PATH),
        hotels_written=len(properties),
    )


if __name__ == "__main__":
    asyncio.run(main())
