"""Parse JSON returned by LLMs, tolerating markdown code fences.

Models frequently wrap JSON in ```json … ``` fences despite being told not to.
`json.loads` then throws and callers silently fall back to defaults — which
previously caused the router to classify almost everything as "unknown".
"""

from __future__ import annotations

import json
import re

_FENCE_OPEN = re.compile(r"^```[a-zA-Z]*\n?")
_FENCE_CLOSE = re.compile(r"\n?```$")


def parse_llm_json(raw: str) -> dict:
    """Return the JSON object in `raw`, stripping code fences. {} on failure."""
    s = raw.strip()
    if s.startswith("```"):
        s = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", s)).strip()
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
