"""Regression tests for option-selection detection.

A bare digit must NOT count as a selection, otherwise "make it 2 nights"
would hijack a booking into selecting option 2.
"""

from app.agent.nodes.extract_params import _detect_selected_option

OPTS = [{"property_id": "a"}, {"property_id": "b"}, {"property_id": "c"}]


def test_explicit_option():
    assert _detect_selected_option("Option 2", OPTS) == 2


def test_ordinal_word():
    assert _detect_selected_option("the second one", OPTS) == 2


def test_hash_number():
    assert _detect_selected_option("#3 please", OPTS) == 3


def test_bare_digit_is_not_a_selection():
    assert _detect_selected_option("make it 2 nights", OPTS) is None
    assert _detect_selected_option("for 3 guests", OPTS) is None
    assert _detect_selected_option("1 king bed", OPTS) is None


def test_confirm_with_single_option():
    assert _detect_selected_option("yes, book it", [{"property_id": "a"}]) == 1


def test_confirm_with_multiple_options_is_ambiguous():
    assert _detect_selected_option("book it", OPTS) is None


def test_no_options_means_no_selection():
    assert _detect_selected_option("Option 1", []) is None
