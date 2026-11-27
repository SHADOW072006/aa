"""
Property-based tests for app/services/pivot_service.py::extract_pivot_candidates

**Validates: Requirements 4.1, 4.3**

Uses hypothesis to verify universal properties hold across arbitrary text inputs.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.pivot_service import extract_pivot_candidates

# ---------------------------------------------------------------------------
# Known valid candidate types
# ---------------------------------------------------------------------------

KNOWN_TYPES = {"phone", "telegram_handle", "telegram_link", "email", "url_domain"}


# ---------------------------------------------------------------------------
# Property 1: Result is always a list
# ---------------------------------------------------------------------------

@given(st.text(max_size=500))
@settings(max_examples=200)
def test_result_is_always_a_list(text: str) -> None:
    """
    **Validates: Requirements 4.1, 4.3**

    extract_pivot_candidates always returns a list, regardless of input.
    """
    result = extract_pivot_candidates(text, "chan")
    assert isinstance(result, list), (
        f"Expected list, got {type(result).__name__!r} for input {text!r}"
    )


# ---------------------------------------------------------------------------
# Property 2: All result dicts have the required keys
# ---------------------------------------------------------------------------

@given(st.text(max_size=500))
@settings(max_examples=200)
def test_all_items_have_required_keys(text: str) -> None:
    """
    **Validates: Requirements 4.1, 4.3**

    Every dict in the result has at least 'candidate_type' and 'candidate_value'.
    """
    result = extract_pivot_candidates(text, "chan")
    for item in result:
        assert "candidate_type" in item, (
            f"Missing 'candidate_type' key in item {item!r}"
        )
        assert "candidate_value" in item, (
            f"Missing 'candidate_value' key in item {item!r}"
        )


# ---------------------------------------------------------------------------
# Property 3: No duplicate (type, value) pairs
# ---------------------------------------------------------------------------

@given(st.text(max_size=500))
@settings(max_examples=200)
def test_no_duplicate_type_value_pairs(text: str) -> None:
    """
    **Validates: Requirements 4.1, 4.3**

    The result contains no two entries with the same (candidate_type, candidate_value).
    """
    result = extract_pivot_candidates(text, "chan")
    seen: set[tuple[str, str]] = set()
    for item in result:
        pair = (item["candidate_type"], item["candidate_value"])
        assert pair not in seen, (
            f"Duplicate (type, value) pair found: {pair!r} in results for input {text!r}"
        )
        seen.add(pair)


# ---------------------------------------------------------------------------
# Property 4: candidate_type is always a known string
# ---------------------------------------------------------------------------

@given(st.text(max_size=500))
@settings(max_examples=200)
def test_candidate_type_is_known_string(text: str) -> None:
    """
    **Validates: Requirements 4.1, 4.3**

    Every candidate_type in the result is one of the known type strings.
    """
    result = extract_pivot_candidates(text, "chan")
    for item in result:
        assert item["candidate_type"] in KNOWN_TYPES, (
            f"Unknown candidate_type {item['candidate_type']!r} "
            f"(allowed: {KNOWN_TYPES}) for input {text!r}"
        )


# ---------------------------------------------------------------------------
# Property 5: Empty string always returns empty list
# ---------------------------------------------------------------------------

def test_empty_string_always_returns_empty_list() -> None:
    """
    **Validates: Requirements 4.1, 4.3**

    extract_pivot_candidates("", "chan") == []
    """
    result = extract_pivot_candidates("", "chan")
    assert result == [], f"Expected [], got {result!r}"


# ---------------------------------------------------------------------------
# Property 6: Whitespace-only always returns empty list
# ---------------------------------------------------------------------------

@given(st.text(alphabet=st.characters(whitelist_categories=("Zs", "Cc")), max_size=100))
@settings(max_examples=100)
def test_whitespace_only_returns_empty_list(text: str) -> None:
    """
    **Validates: Requirements 4.1, 4.3**

    Text composed entirely of whitespace/control characters returns [].
    The fixed case '   \\n\\t  ' is covered as a direct example.
    """
    result = extract_pivot_candidates(text, "chan")
    assert result == [], (
        f"Expected [] for whitespace-only input {text!r}, got {result!r}"
    )


def test_explicit_whitespace_string_returns_empty_list() -> None:
    """
    **Validates: Requirements 4.1, 4.3**

    The literal whitespace string '   \\n\\t  ' returns [].
    """
    result = extract_pivot_candidates("   \n\t  ", "chan")
    assert result == [], f"Expected [], got {result!r}"
