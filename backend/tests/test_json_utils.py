"""Regression tests: LLMs wrap JSON in markdown fences; parsing must tolerate it.

Previously the router called json.loads() directly on fenced output, threw,
and silently fell back to intent="unknown" — bypassing the whole pipeline.
"""

from app.agent.json_utils import parse_llm_json


def test_plain_json():
    assert parse_llm_json('{"intent": "booking"}') == {"intent": "booking"}


def test_json_with_language_fence():
    assert parse_llm_json('```json\n{"intent": "booking"}\n```') == {"intent": "booking"}


def test_json_with_bare_fence():
    assert parse_llm_json('```\n{"mode": "search"}\n```') == {"mode": "search"}


def test_surrounding_whitespace():
    assert parse_llm_json('  \n{"a": 1}\n  ') == {"a": 1}


def test_unparseable_returns_empty():
    assert parse_llm_json("not json at all") == {}


def test_non_object_returns_empty():
    assert parse_llm_json("[1, 2, 3]") == {}
