"""Extract booking parameters from the conversation into BookingState.

Supports two booking modes:
  - direct: specific hotel name or all of city+dates+guests are known
  - search: vague/browsing — partial info, no specific hotel, unresolved dates

Merge logic preserves info from earlier turns (accumulated state).
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from anthropic import Anthropic

from app.agent.json_utils import parse_llm_json
from app.agent.state import AgentState, BookingState
from app.observability import logger, timed_llm_call

_PROMPT = """Extract booking parameters from the conversation. Today's date is {today}.

Return a JSON object with EXACTLY these keys (use null for anything not specified):
{{
  "mode": "direct" | "search",
  "property_name": string | null,
  "city": string | null,
  "check_in": "YYYY-MM-DD" | null,
  "check_out": "YYYY-MM-DD" | null,
  "guests": integer | null,
  "max_price_per_night": number | null,
  "preferences": [string, ...],
  "location_hints": [string, ...],
  "vibe_hints": [string, ...],
  "date_range_hint": string | null,
  "min_nights": integer | null
}}

Mode decision rules (follow precisely):
- Use "search" if ANY of the following is true:
  • No specific hotel name is mentioned (user is browsing, not naming a property)
  • guests is null — the user did not state a number of guests
  • Dates are vague or unresolved ("next month", "late July", "a weekend in June")
  • The user is exploring options rather than booking a known property
- Use "direct" ONLY when ALL of the following are true:
  • A specific hotel name IS mentioned (e.g. "Vibe Sydney", "Adina Bondi") OR
    city + check_in + check_out + guests are ALL explicitly stated by the user
  • guests is an explicit number stated by the user — never infer or default it

Default to "search" when in doubt.

Field rules:
- Resolve relative dates ("next weekend", "this Friday") to absolute ISO dates.
- If the user says "2 nights from Fri 15 June", compute check_in and check_out.
- Do NOT invent values. If the user hasn't said it, the field is null (or empty list for arrays).
- city: lowercase destination city name.
- property_name: the hotel brand/name as stated by the user (e.g. "Vibe Sydney", "Adina Melbourne").
- location_hints: geographic or environment clues ["beach", "CBD", "harbour", "city centre", "Sydney"].
- vibe_hints: mood/purpose clues ["romantic", "family", "business", "boutique", "pet-friendly"].
- date_range_hint: unresolved human-readable date reference ("June 2026", "next weekend", "late July").
- min_nights: minimum stay length if inferable.
- preferences: amenity/style preferences ["near beach", "gym", "pool", "parking"].

Reply with ONLY the JSON object, no prose, no markdown fences."""


# Patterns for detecting selected_option from a user message. These require
# explicit selection language ("option 2", "#2", "the second one") — a bare
# digit is NOT enough, otherwise "make it 2 nights" would hijack a selection.
_OPTION_PATTERNS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"\boption\s*1\b|\bnumber\s*1\b|\bfirst\b|#1\b", re.IGNORECASE), 1),
    (re.compile(r"\boption\s*2\b|\bnumber\s*2\b|\bsecond\b|#2\b", re.IGNORECASE), 2),
    (re.compile(r"\boption\s*3\b|\bnumber\s*3\b|\bthird\b|#3\b", re.IGNORECASE), 3),
    (re.compile(r"\boption\s*4\b|\bnumber\s*4\b|\bfourth\b|#4\b", re.IGNORECASE), 4),
    (re.compile(r"\boption\s*5\b|\bnumber\s*5\b|\bfifth\b|#5\b", re.IGNORECASE), 5),
]
_CONFIRM_PATTERN = re.compile(r"\bbook\s+it\b|\bconfirm\b|\byes\b|\bthat\s+one\b", re.IGNORECASE)


def _client() -> Anthropic:
    return Anthropic()


def _merge(existing: BookingState | None, incoming: dict) -> BookingState:
    """Merge new extraction into existing booking state, preferring non-null incoming."""
    out: BookingState = dict(existing or {})  # type: ignore[assignment]
    out.setdefault("preferences", [])
    for k, v in incoming.items():
        if v is None or v == [] or v == "":
            continue
        if k == "preferences" and isinstance(v, list):
            # Union preferences
            prev = out.get("preferences") or []
            out["preferences"] = sorted(set(prev) | set(v))
        else:
            out[k] = v
    return out


def _detect_selected_option(text: str, available_options: list[dict]) -> int | None:
    """Return 1-indexed selected option number if the user's message picks one."""
    if not available_options:
        return None

    for pattern, option_num in _OPTION_PATTERNS:
        if pattern.search(text) and option_num <= len(available_options):
            return option_num

    # "book it" / "confirm" / "yes" / "that one" — default to option 1 if only one option exists
    if _CONFIRM_PATTERN.search(text) and len(available_options) == 1:
        return 1

    return None


async def run(state: AgentState) -> dict:
    model = os.getenv("AGENT_MODEL", "claude-sonnet-4-6")
    messages = state.get("messages", [])
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages[-10:])

    prompt = _PROMPT.format(today=datetime.utcnow().date().isoformat())

    with timed_llm_call(model=model, node="extract_params") as usage:
        resp = _client().messages.create(
            model=model,
            max_tokens=400,
            system=prompt,
            messages=[{"role": "user", "content": f"Conversation:\n{convo}"}],
        )
        usage["input_tokens"] = resp.usage.input_tokens
        usage["output_tokens"] = resp.usage.output_tokens

    raw = resp.content[0].text if resp.content else ""
    parsed = parse_llm_json(raw)
    if not parsed:
        logger.warning("extract_params_parse_fail", raw=raw)

    # --- Build / update booking_in_progress (direct-mode fields) ---
    direct_fields = {
        k: parsed.get(k)
        for k in ("city", "check_in", "check_out", "guests", "max_price_per_night", "preferences")
    }
    merged = _merge(state.get("booking_in_progress"), direct_fields)
    logger.info("extract_params", merged=merged)

    # --- Build search_criteria (search-mode + mode metadata) ---
    search_criteria: dict = {
        "mode": parsed.get("mode", "direct"),
        "property_name": parsed.get("property_name"),
        "location_hints": parsed.get("location_hints") or [],
        "vibe_hints": parsed.get("vibe_hints") or [],
        "date_range_hint": parsed.get("date_range_hint"),
        "min_nights": parsed.get("min_nights"),
    }

    # Merge with existing search_criteria (preserve accumulated hints)
    existing_criteria = state.get("search_criteria") or {}
    for hints_key in ("location_hints", "vibe_hints"):
        prev_hints: list[str] = existing_criteria.get(hints_key) or []
        new_hints: list[str] = search_criteria.get(hints_key) or []
        search_criteria[hints_key] = sorted(set(prev_hints) | set(new_hints))
    # Mode + scalars: prefer newly extracted non-null values
    for scalar_key in ("mode", "property_name", "date_range_hint", "min_nights"):
        if search_criteria.get(scalar_key) is None and existing_criteria.get(scalar_key) is not None:
            search_criteria[scalar_key] = existing_criteria[scalar_key]

    # --- Detect selected_option from latest user message ---
    updates: dict = {
        "booking_in_progress": merged,
        "search_criteria": search_criteria,
    }

    latest_user_text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            latest_user_text = m.get("content", "")
            break

    if latest_user_text:
        available_options: list[dict] = state.get("available_options") or []
        selected = _detect_selected_option(latest_user_text, available_options)
        if selected is not None:
            logger.info("extract_params_selected_option", selected=selected)
            updates["selected_option"] = selected

    return updates
