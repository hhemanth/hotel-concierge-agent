"""TFE Hotels public website scraper (Australia + New Zealand properties).

Discovers hotel pages from the published sitemap and extracts structured data
from each page's JSON-LD (schema.org ``Hotel`` + ``FAQPage`` blocks), with the
on-page meta description and amenity list as supplements. Only properties whose
JSON-LD ``addressCountry`` is Australia or New Zealand are kept.

Writes ``properties_scraped.json`` in this directory. Best-effort: individual
page failures are logged and skipped; if the whole run fails the output file is
still written (empty list) so downstream code never crashes.

Data source: TFE Hotels public website (tfehotels.com).
Honesty note: data scraped from public pages; may not reflect current listings.
This is NOT TFE's real production system — it is a portfolio demo.

Usage:
    cd backend
    python -m app.data.scrape_tfe
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from app.observability import logger

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.tfehotels.com"
SITEMAP_URL = "https://www.tfehotels.com/generate/sitemap.xml"
USER_AGENT = "TFE-Portfolio-Demo/1.0"
# JSON-LD addressCountry is inconsistent across the site ("Australia" vs
# "New-zealand"), so we compare on a normalised form (letters only, lowercased).
TARGET_COUNTRIES = {"australia", "newzealand"}
REQUEST_DELAY = 0.4  # seconds between page requests (politeness)
OUTPUT_PATH = Path(__file__).parent / "properties_scraped.json"
URL_LIST_PATH = Path(__file__).parent / "hotel_urls.txt"

# Disallowed path prefixes from tfehotels.com/robots.txt (User-agent: *). Python's
# stdlib robotparser mis-parses this particular file and blocks everything, so we
# enforce the rules explicitly. Hotel detail pages and the sitemap are allowed.
_DISALLOWED_PREFIXES = (
    "/admin/",
    "/en/admin/",
    "/en/save-10/",
    "/benefitme/",
    "/en/benefitme/",
    "/en/deals/",
    "/goglobal",
    "/en/hospital-and-university/",
    "/en/registration-card/",
    "/en/hotels/travelodge-hotels/hotel-closure/",
    "/en/careers/teamhub/wagestream/",
    "/contact/eclub/",
    "/en/member-survey-giveaway/",
    "/de/member-survey-giveaway/",
    "/hotels-with-stories/",
)

# schema.org priceRange ($–$$$$) → indicative nightly rate (AUD). The real site
# does not publish nightly rates statically; bookings are mocked downstream.
_PRICE_RANGE_AUD = {"$": 150.0, "$$": 220.0, "$$$": 320.0, "$$$$": 480.0}
_DEFAULT_PRICE_AUD = 300.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _can_fetch(url: str) -> bool:
    """Return True if robots.txt permits fetching this URL (explicit prefix check)."""
    path = urlparse(url).path
    return not any(path.startswith(prefix) for prefix in _DISALLOWED_PREFIXES)


def _is_hotel_detail_url(url: str) -> bool:
    """True for /en/hotels/{brand}/{location}/ — exactly 4 path segments.

    Excludes brand landing pages (3 segments) and sub-pages such as /dining/,
    /weddings/, /meetings-events/ (5 segments), plus all non-English locales.
    """
    parsed = urlparse(url)
    if parsed.netloc != urlparse(BASE_URL).netloc:
        return False
    segments = [s for s in parsed.path.split("/") if s]
    return len(segments) == 4 and segments[0] == "en" and segments[1] == "hotels"


# ---------------------------------------------------------------------------
# JSON-LD + page extraction
# ---------------------------------------------------------------------------


def _parse_jsonld(soup: BeautifulSoup) -> tuple[dict | None, list[dict]]:
    """Return (hotel_block, faqs) from the page's JSON-LD scripts."""
    hotel: dict | None = None
    faqs: list[dict] = []
    for block in soup.find_all("script", type="application/ld+json"):
        if not block.string:
            continue
        try:
            data = json.loads(block.string)
        except json.JSONDecodeError:
            continue
        for entry in data if isinstance(data, list) else [data]:
            if not isinstance(entry, dict):
                continue
            if entry.get("@type") == "Hotel" and hotel is None:
                hotel = entry
            elif entry.get("@type") == "FAQPage":
                for q in entry.get("mainEntity", []):
                    question = (q.get("name") or "").strip()
                    answer = ((q.get("acceptedAnswer") or {}).get("text") or "").strip()
                    if question and answer:
                        faqs.append({"question": question, "answer": answer})
    return hotel, faqs


def _extract_amenities(soup: BeautifulSoup) -> tuple[list[str], str, str, str | None]:
    """Return (amenities, check_in, check_out, parking) from the amenity list.

    The on-page amenity list mixes real amenities with check-in/out times and a
    parking line, so we split those out while keeping them discoverable.
    """
    raw = [
        i.get_text(" ", strip=True)
        for i in soup.select("[class*=amenit] li")
        if i.get_text(strip=True)
    ]
    amenities: list[str] = []
    check_in, check_out = "14:00", "11:00"
    parking: str | None = None

    for item in raw:
        ci = re.match(r"check[\s\-]?in[:\s]+(\d{1,2})[.:](\d{2})", item, re.IGNORECASE)
        co = re.match(r"check[\s\-]?out[:\s]+(\d{1,2})[.:](\d{2})", item, re.IGNORECASE)
        if ci:
            check_in = f"{int(ci.group(1)):02d}:{ci.group(2)}"
            continue
        if co:
            check_out = f"{int(co.group(1)):02d}:{co.group(2)}"
            continue
        if re.search(r"parking", item, re.IGNORECASE):
            parking = item
        amenities.append(item)

    return amenities, check_in, check_out, parking


def _meta_description(soup: BeautifulSoup) -> str:
    tag = soup.select_one("meta[name='description']")
    return (tag.get("content") if tag else "") or ""


def _pet_policy(soup: BeautifulSoup) -> str:
    text = soup.get_text(" ")
    if re.search(r"\bpet[\s\-]?friendly\b", text, re.IGNORECASE):
        return "Pets welcome"
    return "Contact the hotel for its pet policy"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_property(hotel: dict, faqs: list[dict], soup: BeautifulSoup) -> dict:
    name = (hotel.get("name") or "").strip()
    address = hotel.get("address") or {}
    city = (address.get("addressLocality") or "").strip()
    street = (address.get("streetAddress") or "").strip()
    # The suburb/neighbourhood is usually the trailing comma-segment of the street.
    neighbourhood = street.split(",")[-1].strip() if "," in street else ""

    amenities, check_in, check_out, parking = _extract_amenities(soup)
    description = (hotel.get("description") or "").strip() or _meta_description(soup)
    rating = _float_or_none((hotel.get("aggregateRating") or {}).get("ratingValue"))
    price = _PRICE_RANGE_AUD.get((hotel.get("priceRange") or "").strip(), _DEFAULT_PRICE_AUD)

    full_address = ", ".join(
        part for part in (street, city, address.get("postalCode")) if part
    )

    return {
        "property_id": _slugify(name),
        "name": name,
        "city": city.lower(),
        "neighbourhood": neighbourhood,
        "max_guests": 4,
        "rating": round(rating, 1) if rating is not None else None,
        "price_per_night": price,
        "amenities": amenities,
        "description": description,
        "check_in_time": check_in,
        "check_out_time": check_out,
        "pet_policy": _pet_policy(soup),
        "parking": parking or "Contact the hotel for parking details",
        "address": full_address,
        "image_url": hotel.get("image") or None,
        "latitude": _float_or_none(hotel.get("latitude")),
        "longitude": _float_or_none(hotel.get("longitude")),
        "phone": (hotel.get("telephone") or "").strip() or None,
        "faqs": faqs,
        "source": "scraped:tfehotels.com",
    }


# ---------------------------------------------------------------------------
# Page-level scraping
# ---------------------------------------------------------------------------


async def _get_hotel_urls(client: httpx.AsyncClient) -> list[str]:
    """Return hotel detail URLs from the local list file, falling back to the sitemap."""
    if URL_LIST_PATH.exists():
        urls = [
            line.strip()
            for line in URL_LIST_PATH.read_text().splitlines()
            if line.strip() and _is_hotel_detail_url(line.strip())
        ]
        if urls:
            logger.info("hotel_urls_loaded", source=str(URL_LIST_PATH), count=len(urls))
            return list(dict.fromkeys(urls))

    try:
        resp = await client.get(SITEMAP_URL)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sitemap_failed", url=SITEMAP_URL, error=str(exc))
        return []

    locs = re.findall(r"<loc>([^<]+)</loc>", resp.text)
    urls = [u for u in locs if _is_hotel_detail_url(u)]
    deduped = list(dict.fromkeys(urls))
    logger.info("hotel_urls_found", count=len(deduped))
    return deduped


async def _scrape_hotel_page(client: httpx.AsyncClient, url: str) -> dict | None:
    """Scrape one hotel page; return a property dict only for AU properties."""
    if not _can_fetch(url):
        logger.warning("robots_disallowed", url=url)
        return None
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("hotel_page_failed", url=url, error=str(exc))
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    hotel, faqs = _parse_jsonld(soup)
    if hotel is None or not (hotel.get("name") or "").strip():
        return None  # not a real hotel detail page (e.g. listing/redirect)

    country_raw = ((hotel.get("address") or {}).get("addressCountry") or "")
    country = re.sub(r"[^a-z]", "", country_raw.lower())
    if country not in TARGET_COUNTRIES:
        return None  # keep Australian + New Zealand properties only

    prop = _build_property(hotel, faqs, soup)
    logger.info("hotel_scraped", name=prop["name"], city=prop["city"], n_faqs=len(faqs))
    return prop


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    properties: list[dict] = []
    try:
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(
            headers=headers, follow_redirects=True, timeout=20.0
        ) as client:
            hotel_urls = await _get_hotel_urls(client)
            if not hotel_urls:
                logger.warning("no_hotel_urls_found", base=BASE_URL)

            for url in hotel_urls:
                result = await _scrape_hotel_page(client, url)
                if result is not None:
                    properties.append(result)
                await asyncio.sleep(REQUEST_DELAY)
    except Exception as exc:  # noqa: BLE001
        logger.warning("scraper_failed", error=str(exc), hotels_collected=len(properties))

    OUTPUT_PATH.write_text(json.dumps(properties, indent=2, ensure_ascii=False))
    logger.info("scrape_complete", output=str(OUTPUT_PATH), hotels_written=len(properties))


if __name__ == "__main__":
    asyncio.run(main())
