"""Thin loader that prefers scraped data over synthetic fallback."""
from __future__ import annotations

import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent
_SCRAPED = _DATA_DIR / "properties_scraped.json"
_SYNTHETIC = _DATA_DIR / "properties.json"


def load_properties() -> list[dict]:
    """Return scraped properties if available, else synthetic fallback."""
    path = _SCRAPED if _SCRAPED.exists() else _SYNTHETIC
    return json.loads(path.read_text())
