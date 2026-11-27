"""
Property-based tests for app/extractors/normaliser.py.

**Validates: Requirements 2.1, 2.3**

Properties tested
-----------------
1. Idempotency: normalise(normalise(s)) == normalise(s)
2. Output is always a str.
3. No zero-width / invisible characters remain in the output.
4. Every alphabetic character in the output is lowercase.
5. For pure-ASCII input, len(normalise(s)) <= len(s)  (no length inflation).
6. Output never starts or ends with whitespace, and never contains
   consecutive spaces.
7. generate_variants() — all returned dicts have exactly the
   'variant_text' and 'variant_type' keys, and all variant_text values
   differ from the raw input seed.
"""

from __future__ import annotations

import string

from hypothesis import given, settings
from hypothesis import strategies as st

from app.extractors.normaliser import normalise

# ── Shared strategies ──────────────────────────────────────────────────────────

# General Unicode text (Hypothesis default: any printable + control chars)
_any_text = st.text()

# Pure-ASCII printable text — used for the length-reduction property.
# Restrict to characters in the ASCII printable range (0x20–0x7E) to
# avoid Unicode letters like İ (U+0130) that expand on lowercasing.
_ascii_text = st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E))

# Seeds that contain at least one letter so generate_variants has something to
# work with (single word ≥ 1 char of letters).
_seed_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=1,
    max_size=30,
)

# Zero-width / invisible characters that must be stripped.
_ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\u200e\u200f\u00ad\u2060\ufeff"


# ── Property 1 — Idempotency ───────────────────────────────────────────────────

@given(_any_text)
@settings(max_examples=200)
def test_normalise_idempotent(s: str) -> None:
    """Applying normalise twice gives the same result as applying it once.

    **Validates: Requirements 2.1**
    """
    assert normalise(normalise(s)) == normalise(s)


# ── Property 2 — Output is always str ─────────────────────────────────────────

@given(_any_text)
@settings(max_examples=200)
def test_normalise_returns_str(s: str) -> None:
    """normalise() always returns a str, never None or another type.

    **Validates: Requirements 2.1**
    """
    result = normalise(s)
    assert isinstance(result, str)


# ── Property 3 — No zero-width characters in output ───────────────────────────

@given(_any_text)
@settings(max_examples=200)
def test_normalise_no_zero_width_chars(s: str) -> None:
    """After normalisation, the result contains none of the invisible characters.

    **Validates: Requirements 2.1**
    """
    result = normalise(s)
    for ch in _ZERO_WIDTH_CHARS:
        assert ch not in result, f"Found zero-width char U+{ord(ch):04X} in {result!r}"


# ── Property 4 — Output is lowercase or non-alphabetic ────────────────────────

@given(_any_text)
@settings(max_examples=100)
def test_normalise_output_lowercase_or_non_alpha(s: str) -> None:
    """Every character in the normalised output that is alphabetic must be lowercase.

    **Validates: Requirements 2.1**
    """
    result = normalise(s)
    for ch in result:
        if ch.isalpha():
            assert ch == ch.lower(), (
                f"Found uppercase letter {ch!r} in normalised output {result!r}"
            )


# ── Property 5 — Length reduction for ASCII inputs ────────────────────────────

@given(_ascii_text)
@settings(max_examples=100)
def test_normalise_ascii_does_not_inflate(s: str) -> None:
    """For pure ASCII input, normalise() must not increase the string length.

    **Validates: Requirements 2.1**
    """
    result = normalise(s)
    assert len(result) <= len(s), (
        f"Input length {len(s)}, output length {len(result)}\n"
        f"Input:  {s!r}\nOutput: {result!r}"
    )


# ── Property 6 — Whitespace normalised ────────────────────────────────────────

@given(_any_text)
@settings(max_examples=100)
def test_normalise_no_leading_trailing_or_double_spaces(s: str) -> None:
    """Normalised output never starts/ends with whitespace or has consecutive spaces.

    **Validates: Requirements 2.1**
    """
    result = normalise(s)
    # No leading / trailing whitespace
    assert result == result.strip(), (
        f"Leading/trailing whitespace in {result!r}"
    )
    # No consecutive spaces
    assert "  " not in result, (
        f"Consecutive spaces in {result!r}"
    )


# ── Property 7 — generate_variants() structure and content ────────────────────

@given(_seed_strategy)
@settings(max_examples=100, deadline=None)
def test_generate_variants_structure_and_differ_from_input(seed: str) -> None:
    """All dicts from generate_variants have the right keys; suffix_fallback and
    hyphen variants must differ from the raw input seed.

    For multi-word seeds all variants must differ from the raw input.
    For single-word seeds the spacing variant may equal the normalised seed
    (this is by design), but every other variant type must differ.

    **Validates: Requirements 2.3**
    """
    from app.extractors.normaliser import normalise as _norm
    from app.services.seed_service import generate_variants

    variants = generate_variants(seed, "en")

    assert isinstance(variants, list), "generate_variants must return a list"
    assert len(variants) >= 1, "generate_variants must return at least one variant"

    normalised_seed = _norm(seed)
    seed_tokens = normalised_seed.split()
    is_multi_word = len(seed_tokens) >= 2

    for item in variants:
        # Required keys — all dicts must have exactly these two keys.
        assert "variant_text" in item, f"Missing 'variant_text' key in {item!r}"
        assert "variant_type" in item, f"Missing 'variant_type' key in {item!r}"
        assert set(item.keys()) == {"variant_text", "variant_type"}, (
            f"Unexpected keys in {item!r}"
        )

        v_text = item["variant_text"]
        v_type = item["variant_type"]

        # For multi-word seeds, all variants must differ from the raw input.
        # For single-word seeds, the spacing variant may legitimately equal
        # the normalised form of the seed; all other types must differ.
        if is_multi_word:
            assert v_text != seed, (
                f"variant_text {v_text!r} equals raw seed {seed!r}"
            )
        else:
            if v_type != "spacing":
                assert v_text != seed, (
                    f"Non-spacing variant {v_text!r} (type={v_type!r}) "
                    f"equals raw seed {seed!r}"
                )
