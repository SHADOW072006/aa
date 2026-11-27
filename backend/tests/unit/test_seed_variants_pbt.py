"""
Property-based tests for generate_variants() in seed_service.py.

**Validates: Requirements 2.2, 2.4**

Properties tested
-----------------
1. For multi-word seeds, no non-spacing variant equals the full normalised seed.
   (Single-token seeds legitimately emit the token itself as the spacing anchor;
   the meaningful uniqueness guarantee applies to multi-word seeds where
   hyphen, transliteration, and suffix_fallback variants must differ from the
   full normalised seed string.)
2. All variant_text values are non-empty strings with len > 0.
3. No duplicate variant_text within the returned list.
4. All variant_type values are members of the known type set.
5. All variant_text values are of type str.
6. For seeds that contain a space after normalisation, at least one variant
   is returned.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.extractors.normaliser import normalise as normalise_seed
from app.services.seed_service import generate_variants

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWN_VARIANT_TYPES = {
    "spacing",
    "hyphen",
    "transliteration_to_latin",
    "transliteration_to_devanagari",
    "suffix_fallback",
}

# Strategy: Unicode letter characters, 4–20 codepoints, with possible
# embedded spaces so we exercise both single- and multi-word paths.
_seed_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=4,
    max_size=20,
)

# Multi-word seeds: insert at least one space between letter runs.
_multiword_strategy = st.builds(
    lambda a, b: f"{a} {b}",
    st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=2, max_size=9),
    st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=2, max_size=9),
)


# ---------------------------------------------------------------------------
# Property 1 — For multi-word seeds, non-spacing variants differ from full normalised seed
# ---------------------------------------------------------------------------

@given(_multiword_strategy)
@settings(max_examples=200)
def test_no_variant_equals_full_normalised_multiword_seed(seed: str) -> None:
    """
    **Validates: Requirements 2.2**

    For multi-word seeds, non-spacing variants (hyphen, suffix_fallback,
    transliteration) must not reproduce the full normalised seed verbatim.
    Spacing variants are 2-token slices of the seed, so for 2-token seeds
    the spacing variant IS a 2-token slice — but hyphen and other types
    must differ from the original.

    Single-token seeds are excluded because the implementation legitimately
    emits the token itself as the spacing anchor before appending suffix
    fallbacks.
    """
    normalised = normalise_seed(seed)
    tokens = normalised.split()

    # Only assert for seeds that remain multi-word after normalisation.
    if len(tokens) < 2:
        return

    variants = generate_variants(seed, "en")
    for item in variants:
        if item["variant_type"] not in ("spacing",):
            assert item["variant_text"] != normalised, (
                f"Non-spacing variant {item['variant_text']!r} (type={item['variant_type']!r}) "
                f"equals normalised seed {normalised!r} for input {seed!r}"
            )


# ---------------------------------------------------------------------------
# Property 2 — All variant_text values are non-empty strings (len > 0)
# ---------------------------------------------------------------------------

@given(_seed_strategy)
@settings(max_examples=200)
def test_all_variant_texts_are_nonempty(seed: str) -> None:
    """
    **Validates: Requirements 2.2**

    Every returned variant_text has at least one character (len > 0).
    """
    variants = generate_variants(seed, "en")
    for item in variants:
        text = item["variant_text"]
        assert len(text) > 0, f"Empty variant_text found for seed {seed!r}"
        assert text.strip() != "", (
            f"Whitespace-only variant_text found for seed {seed!r}"
        )


# ---------------------------------------------------------------------------
# Property 3 — No duplicate variant_text in the returned list
# ---------------------------------------------------------------------------

@given(_seed_strategy)
@settings(max_examples=200)
def test_no_duplicate_variant_texts(seed: str) -> None:
    """
    **Validates: Requirements 2.2**

    The variant_text values are globally unique within the list returned
    for any single seed.
    """
    variants = generate_variants(seed, "en")
    texts = [item["variant_text"] for item in variants]
    assert len(texts) == len(set(texts)), (
        f"Duplicates found in variants for seed {seed!r}: {texts}"
    )


# ---------------------------------------------------------------------------
# Property 4 — All variant_type values are known strings
# ---------------------------------------------------------------------------

@given(_seed_strategy)
@settings(max_examples=200)
def test_all_variant_types_are_known(seed: str) -> None:
    """
    **Validates: Requirements 2.2**

    Every variant_type must be one of the five documented type strings.
    """
    variants = generate_variants(seed, "en")
    for item in variants:
        assert item["variant_type"] in KNOWN_VARIANT_TYPES, (
            f"Unknown variant_type {item['variant_type']!r} for seed {seed!r}"
        )


# ---------------------------------------------------------------------------
# Property 5 — All variant_text values are instances of str
# ---------------------------------------------------------------------------

@given(_seed_strategy)
@settings(max_examples=200)
def test_all_variant_texts_are_str(seed: str) -> None:
    """
    **Validates: Requirements 2.2**

    variant_text must always be a plain Python str.
    """
    variants = generate_variants(seed, "en")
    for item in variants:
        assert isinstance(item["variant_text"], str), (
            f"variant_text is not str: {type(item['variant_text'])} for seed {seed!r}"
        )


# ---------------------------------------------------------------------------
# Property 6 — Multi-word seeds produce at least one variant
# ---------------------------------------------------------------------------

@given(_multiword_strategy)
@settings(max_examples=200)
def test_multiword_seeds_produce_at_least_one_variant(seed: str) -> None:
    """
    **Validates: Requirements 2.4**

    For any seed that contains a space character (guaranteed by the strategy),
    generate_variants must return a non-empty list.
    """
    # Confirm the seed has a space (the strategy guarantees this, but be explicit)
    assert " " in seed, f"Strategy broken: seed has no space: {seed!r}"
    variants = generate_variants(seed, "en")
    assert len(variants) > 0, (
        f"No variants produced for multi-word seed {seed!r}"
    )
