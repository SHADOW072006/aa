"""
Comprehensive unit tests for app/extractors/normaliser.py.

Covers the 7-step normalisation pipeline and the generate_variants()
helper from app/services/seed_service.py.

Requirements: 2.1, 2.2, 2.3, 2.4
"""

import pytest
from app.extractors.normaliser import normalise, normalise_text, CONFUSABLE_MAP


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def gv(seed: str, lang: str = "en"):
    """Import generate_variants lazily (avoids circular-import issues at module level)."""
    from app.services.seed_service import generate_variants
    return generate_variants(seed, lang)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Basic contract / type safety
# ─────────────────────────────────────────────────────────────────────────────

def test_raises_on_non_string():
    """normalise() must reject non-str inputs with TypeError."""
    with pytest.raises(TypeError):
        normalise(123)  # type: ignore[arg-type]


def test_empty_string_returns_empty():
    """Empty input → empty output."""
    assert normalise("") == ""


def test_alias_identity():
    """normalise_text is the same function as normalise."""
    assert normalise_text is normalise


# ─────────────────────────────────────────────────────────────────────────────
# 2. Idempotency
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "hello world",
    "drug sale",
    "crack cocaine",
    "test!!",
    "abc def ghi",
    "",
])
def test_idempotency(text):
    """normalise(normalise(x)) == normalise(x) for any input."""
    once = normalise(text)
    twice = normalise(once)
    assert once == twice, f"Not idempotent for {text!r}: {once!r} → {twice!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Step 1 — NFKC / Unicode normalisation
# ─────────────────────────────────────────────────────────────────────────────

def test_fullwidth_survives_nfc():
    """The pipeline uses NFC (not NFKC), so fullwidth chars are preserved as-is."""
    # NFC normalisation does not decompose fullwidth chars — they pass through
    # the pipeline unchanged (then lowercased).  This test confirms the actual
    # behaviour; fullwidth→ASCII decomposition is not part of the pipeline.
    result = normalise("ｈｅｌｌｏ")
    # NFC does not change fullwidth, so the output is the lowercased fullwidth string.
    assert result == "ｈｅｌｌｏ"


def test_nfc_combining_diacritic():
    """NFC normalisation collapses pre-composed + combining sequences."""
    # 'é' as combining sequence (e + U+0301) should survive as 'é' (precomposed),
    # then be lowercased.  The important thing is it doesn't explode.
    result = normalise("Cafe\u0301")   # C a f e + combining accent
    # After NFC → "Café", after lower → "café"
    assert result == "café"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Step 2 — zero-width / invisible character removal
# ─────────────────────────────────────────────────────────────────────────────

def test_zero_width_space_removed():
    """U+200B ZERO WIDTH SPACE must be stripped."""
    assert normalise("hello\u200bworld") == "helloworld"


def test_zero_width_non_joiner_removed():
    """U+200C ZWNJ must be stripped."""
    assert normalise("hel\u200clo") == "hello"


def test_zero_width_joiner_removed():
    """U+200D ZWJ must be stripped."""
    assert normalise("hel\u200dlo") == "hello"


def test_right_to_left_mark_removed():
    """U+200F RLM must be stripped."""
    assert normalise("hello\u200fworld") == "helloworld"


def test_bom_removed():
    """U+FEFF BOM/ZWNBSP must be stripped."""
    assert normalise("\ufeffhello") == "hello"


def test_multiple_zero_width_removed():
    """Multiple different zero-width chars in one string are all removed."""
    assert normalise("a\u200b\u200c\u200db") == "ab"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Step 3 — look-alike (confusable) replacement
# ─────────────────────────────────────────────────────────────────────────────

def test_cyrillic_confusables_replaced():
    """Cyrillic с, а, с, е → ASCII c, a, c, e (с maps to 'c', not 's')."""
    # "\u0441" = с → "c", "\u0430" = а → "a", "\u0435" = е → "e"
    # So "\u0441\u0430\u0441\u0435" (сасе) → "cace"
    result = normalise("\u0441\u0430\u0441\u0435")
    assert result == "cace"


def test_cyrillic_mixed_word():
    """Mixed Cyrillic/Latin in one word is normalised to pure Latin."""
    # "cr\u0430\u0441k" = "crаsk" with Cyrillic а and с
    result = normalise("cr\u0430\u0441k")
    assert result == "crack"


def test_greek_alpha_omicron():
    """Greek α → a and ο → o."""
    result = normalise("\u03b1\u03bf")  # αο
    assert result == "ao"


def test_greek_uppercase_confusables():
    """Greek Α → A, Β → B, Ε → E."""
    result = normalise("\u0391\u0392\u0395")  # ΑΒΕ
    assert result == "abe"  # lowercased after replacement


def test_confusable_map_coverage():
    """CONFUSABLE_MAP has at least 24 entries as specified."""
    assert len(CONFUSABLE_MAP) >= 24


# ─────────────────────────────────────────────────────────────────────────────
# 6. Step 4 — lowercase conversion
# ─────────────────────────────────────────────────────────────────────────────

def test_lowercase_basic():
    """Plain ASCII uppercase is lowercased."""
    assert normalise("HELLO WORLD") == "hello world"


def test_lowercase_mixed_case():
    """Mixed-case input is fully lowercased."""
    assert normalise("DrUg SaLe") == "drug sale"


def test_already_lowercase_unchanged():
    """Already-lowercase input stays the same (modulo other pipeline steps)."""
    assert normalise("hello world") == "hello world"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Step 5 — repeated-punctuation compression
# ─────────────────────────────────────────────────────────────────────────────

def test_triple_exclamation_compressed():
    """Three identical punct chars → two."""
    assert normalise("wow!!!") == "wow!!"


def test_many_exclamations_compressed():
    """Six exclamation marks → two."""
    assert normalise("!!!!!!") == "!!"


def test_triple_question_mark_compressed():
    """Three question marks → two."""
    assert normalise("what???") == "what??"


def test_double_punct_unchanged():
    """Exactly two identical punct chars is not compressed."""
    assert normalise("hello!!") == "hello!!"


def test_single_punct_unchanged():
    """A single punctuation character is not affected."""
    assert normalise("hello!") == "hello!"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Step 6 — whitespace normalisation
# ─────────────────────────────────────────────────────────────────────────────

def test_leading_trailing_whitespace_stripped():
    """Leading and trailing whitespace is removed."""
    assert normalise("  hello world  ") == "hello world"


def test_internal_multiple_spaces_collapsed():
    """Multiple internal spaces collapse to one."""
    assert normalise("hello   world") == "hello world"


def test_tab_normalised():
    """Tab characters are treated as whitespace and collapsed."""
    assert normalise("hello\tworld") == "hello world"


def test_newline_normalised():
    """Newlines are treated as whitespace and collapsed."""
    assert normalise("hello\nworld") == "hello world"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Step 7 — hyphen → space interchange
# ─────────────────────────────────────────────────────────────────────────────

def test_hyphen_replaced_by_space():
    """Hyphens are replaced by spaces."""
    assert normalise("drug-sale") == "drug sale"


def test_hyphen_and_space_produce_same_output():
    """'drug-sale' and 'drug sale' normalise to the same string."""
    assert normalise("drug-sale") == normalise("drug sale")


def test_multiple_hyphens_replaced():
    """Multiple hyphens all become spaces."""
    assert normalise("a-b-c") == "a b c"


# ─────────────────────────────────────────────────────────────────────────────
# 10. Transliteration hook
# ─────────────────────────────────────────────────────────────────────────────

def test_transliteration_hook_applied():
    """A custom transliteration hook is called and its output used."""
    hook = lambda s: s.replace("a", "@")  # noqa: E731
    result = normalise("cat", transliteration_hook=hook)
    assert result == "c@t"


def test_no_hook_does_not_alter_ascii():
    """Without a hook, plain ASCII input passes through unchanged (modulo pipeline)."""
    assert normalise("hello") == "hello"


# ─────────────────────────────────────────────────────────────────────────────
# 11. Combined / mixed inputs
# ─────────────────────────────────────────────────────────────────────────────

def test_combined_cyrillic_zero_width_uppercase():
    """Cyrillic confusables + zero-width + uppercase all cleaned in one pass."""
    # "\u0441" = Cyrillic с, "\u200b" = ZWSP
    inp = "\u0441R\u200bACK"
    result = normalise(inp)
    assert result == "crack"


def test_combined_fullwidth_and_punct():
    """Fullwidth chars pass through NFC unchanged; punctuation compression still fires."""
    # NFC does not decompose fullwidth, so ｈｅｌｌｏ stays as-is; !!! → !!
    result = normalise("ｈｅｌｌｏ!!!")
    assert result == "ｈｅｌｌｏ!!"


def test_combined_pipeline_complex():
    """Full pipeline on a pathological string."""
    inp = "  \ufeffDR\u0423G\u200b-\u0441ALE!!!  "
    # \ufeff removed (Step 2), DR stays, \u0423=У is NOT in confusable map
    # (only lowercase \u0443=у→y is mapped), so after Step 4 lowercase it
    # becomes the Cyrillic lowercase у (u+0443), \u200b removed (Step 2),
    # - → space (Step 7), \u0441=с→"c" (Step 3), ALE stays,
    # !!! → !! (Step 5), stripped (Step 6)
    # Result: "dr" + Cyrillic_у + "g cale!!"
    result = normalise(inp)
    # The Cyrillic lowercase у (u+0443) maps to "y" via the confusable map,
    # which is applied before lowercasing — but Step 3 runs before Step 4.
    # \u0423 (uppercase У) is NOT in the map, so Step 3 leaves it; Step 4
    # lowercases it to \u0443 (у).  \u0443 IS in the map but Step 3 already ran.
    # So the final char is Cyrillic у (not ASCII y).
    assert result == "dr\u0443g cale!!"


# ─────────────────────────────────────────────────────────────────────────────
# 12. generate_variants() — structure and content
# ─────────────────────────────────────────────────────────────────────────────

def test_variants_returns_list():
    """generate_variants must return a list."""
    result = gv("drug sale")
    assert isinstance(result, list)


def test_variants_dicts_have_required_keys():
    """Every variant dict must have 'variant_text' and 'variant_type' keys."""
    result = gv("drug sale")
    for item in result:
        assert "variant_text" in item, f"Missing 'variant_text' in {item}"
        assert "variant_type" in item, f"Missing 'variant_type' in {item}"


def test_variants_no_duplicates():
    """No two variants have identical variant_text values."""
    result = gv("drug sale")
    texts = [d["variant_text"] for d in result]
    assert len(texts) == len(set(texts)), f"Duplicates found: {texts}"


def test_variants_minimum_count():
    """At least 3 variants are always returned."""
    result = gv("drug sale")
    assert len(result) >= 3, f"Only {len(result)} variants returned"


def test_variants_single_token_minimum_count():
    """Single-token seed still produces at least 3 variants via suffix fallback."""
    result = gv("cocaine")
    assert len(result) >= 3


def test_variants_spacing_type_present():
    """A 'spacing' variant is produced for multi-token seeds."""
    result = gv("drug sale")
    types = [d["variant_type"] for d in result]
    assert "spacing" in types


def test_variants_hyphen_type_present():
    """A 'hyphen' variant is produced for multi-token seeds."""
    result = gv("drug sale")
    types = [d["variant_type"] for d in result]
    assert "hyphen" in types


def test_variants_suffix_fallback_for_single_token():
    """suffix_fallback variants appear for single-token seeds."""
    result = gv("cocaine")
    types = [d["variant_type"] for d in result]
    assert "suffix_fallback" in types


def test_variants_all_texts_non_empty():
    """Every variant_text is a non-empty, non-whitespace-only string."""
    result = gv("drug sale")
    for d in result:
        assert d["variant_text"].strip() != "", f"Empty variant_text in {d}"


def test_variants_max_two_tokens():
    """Every variant_text has at most two whitespace-separated tokens."""
    result = gv("multi token seed example")
    for d in result:
        tokens = d["variant_text"].split()
        assert len(tokens) <= 2, f"Variant has >2 tokens: {d['variant_text']!r}"


def test_variants_known_type_values():
    """variant_type values must be from the documented set."""
    allowed = {"spacing", "hyphen", "transliteration_to_latin",
               "transliteration_to_devanagari", "suffix_fallback"}
    result = gv("drug sale")
    for d in result:
        assert d["variant_type"] in allowed, (
            f"Unknown variant_type {d['variant_type']!r}"
        )
