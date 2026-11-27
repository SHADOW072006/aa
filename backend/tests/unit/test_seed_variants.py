"""
Unit tests for seed variant generation and seed lifecycle.

Requirements: 1.1, 2.1, 2.2, 2.5
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extractors.normaliser import CONFUSABLE_MAP, normalise
from app.services.seed_service import generate_variants

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_VARIANT_TYPES = {
    "spacing",
    "hyphen",
    "transliteration_to_latin",
    "transliteration_to_devanagari",
    "suffix_fallback",
}


def _variant_texts(variants: list[dict]) -> list[str]:
    return [v["variant_text"] for v in variants]


def _variant_types(variants: list[dict]) -> list[str]:
    return [v["variant_type"] for v in variants]


# ===========================================================================
# 1. normalise() — Step 4 lowercase + confusable map
# ===========================================================================


class TestNormalise:
    """Tests for the normalise() function."""

    def test_plain_english_lowercased(self):
        """'Drug Sale' → 'drug sale'."""
        result = normalise("Drug Sale")
        assert result == "drug sale"

    def test_all_caps_lowercased(self):
        """'DRUG SALE' → 'drug sale'."""
        assert normalise("DRUG SALE") == "drug sale"

    def test_cyrillic_confusable_chars_replaced(self):
        """Cyrillic а, е, о, с, х should map to their ASCII look-alikes."""
        # Pick Cyrillic characters present in CONFUSABLE_MAP
        cyrillic_a = "\u0430"  # а → a
        cyrillic_e = "\u0435"  # е → e
        cyrillic_o = "\u043e"  # о → o
        # Build a string using them
        word = cyrillic_a + cyrillic_e + cyrillic_o  # "аео"
        result = normalise(word)
        assert result == "aeo"

    def test_cyrillic_uppercase_confusable_replaced(self):
        """Cyrillic uppercase А (U+0410) → ASCII 'a' after lowercasing."""
        cyrillic_A = "\u0410"  # А → A (then lowercased → a)
        result = normalise(cyrillic_A)
        assert result == "a"

    def test_greek_confusable_chars_replaced(self):
        """Greek α (U+03B1) and ο (U+03BF) → 'a' and 'o'."""
        greek = "\u03b1\u03bf"  # αο
        result = normalise(greek)
        assert result == "ao"

    def test_leading_trailing_spaces_stripped(self):
        """Seed text with leading/trailing spaces is trimmed."""
        result = normalise("  drug sale  ")
        assert result == "drug sale"

    def test_internal_whitespace_collapsed(self):
        """Multiple spaces between words are collapsed to one."""
        result = normalise("drug   sale")
        assert result == "drug sale"

    def test_hyphen_converted_to_space(self):
        """Step 7: hyphens are converted to spaces."""
        result = normalise("drug-sale")
        assert result == "drug sale"

    def test_non_str_input_raises_type_error(self):
        """Non-string input raises TypeError."""
        with pytest.raises(TypeError):
            normalise(123)  # type: ignore[arg-type]

    def test_empty_string_returns_empty(self):
        """Empty string returns empty string."""
        assert normalise("") == ""


# ===========================================================================
# 2. generate_variants() — variant generation
# ===========================================================================


class TestGenerateVariants:
    """Tests for generate_variants() in seed_service."""

    def test_multi_word_produces_hyphen_variant(self):
        """'drug sale' → hyphen variant 'drug-sale' is included."""
        variants = generate_variants("drug sale", "en")
        texts = _variant_texts(variants)
        assert "drug-sale" in texts

    def test_multi_word_produces_spacing_variant(self):
        """'drug sale' → spacing variant 'drug sale' is included."""
        variants = generate_variants("drug sale", "en")
        texts = _variant_texts(variants)
        assert "drug sale" in texts

    def test_hyphenated_input_spacing_variant_has_space(self):
        """'drug-trafficking' normalises to 'drug trafficking'; spacing variant uses spaces."""
        variants = generate_variants("drug-trafficking", "en")
        texts = _variant_texts(variants)
        # Normalisation converts hyphen → space, so tokens are ['drug', 'trafficking']
        # spacing variant = 'drug trafficking'
        assert "drug trafficking" in texts

    def test_single_word_no_hyphen_variant(self):
        """Single-word seed does not generate a hyphen variant."""
        variants = generate_variants("heroin", "en")
        types = _variant_types(variants)
        assert "hyphen" not in types

    def test_single_word_gets_suffix_fallback_variants(self):
        """Single-word seed produces suffix_fallback variants to reach ≥3."""
        variants = generate_variants("heroin", "en")
        assert len(variants) >= 3
        types = _variant_types(variants)
        assert "suffix_fallback" in types

    def test_no_duplicate_variant_texts(self):
        """Variant texts are deduplicated — no text appears twice."""
        variants = generate_variants("drug sale", "en")
        texts = _variant_texts(variants)
        assert len(texts) == len(set(texts))

    def test_result_dicts_have_exactly_two_keys(self):
        """Each result dict has exactly 'variant_text' and 'variant_type' keys."""
        variants = generate_variants("cocaine buy", "en")
        for item in variants:
            assert set(item.keys()) == {"variant_text", "variant_type"}

    def test_all_variant_types_are_known_values(self):
        """variant_type is one of the allowed strings."""
        variants = generate_variants("meth sale", "en")
        for item in variants:
            assert item["variant_type"] in VALID_VARIANT_TYPES

    def test_each_variant_text_at_most_two_tokens(self):
        """No variant has more than two whitespace-separated tokens."""
        variants = generate_variants("drug sale buy cheap", "en")
        for item in variants:
            tokens = item["variant_text"].strip().split()
            assert len(tokens) <= 2, f"Too many tokens: {item['variant_text']!r}"

    def test_non_empty_variant_texts(self):
        """No variant has an empty or whitespace-only variant_text."""
        variants = generate_variants("drug sale", "en")
        for item in variants:
            assert item["variant_text"].strip() != ""

    def test_three_token_seed_produces_adjacent_slices(self):
        """Three-token seed produces spacing variants for each adjacent pair."""
        variants = generate_variants("buy cocaine now", "en")
        texts = _variant_texts(variants)
        # Adjacent slices: 'buy cocaine' and 'cocaine now'
        assert "buy cocaine" in texts
        assert "cocaine now" in texts

    def test_repeated_whitespace_seed_deduplicates(self):
        """Seed with extra whitespace normalises to same as clean version."""
        v1 = generate_variants("drug  sale", "en")
        v2 = generate_variants("drug sale", "en")
        assert _variant_texts(v1) == _variant_texts(v2)


# ===========================================================================
# 3. create_seed() — seed lifecycle (mock DB)
# ===========================================================================


class TestCreateSeed:
    """Tests for create_seed() using an async mock DB session."""

    def _make_db(self):
        """Return a mock AsyncSession."""
        return AsyncMock()

    def _seed_kwargs(self, seed_text: str = "drug sale") -> dict:
        return dict(
            seed_text=seed_text,
            threat_category="drugs",
            language_region="en",
            intent_type="sale",
            priority=3,
            created_source="manual",
        )

    @pytest.mark.asyncio
    async def test_duplicate_seed_raises_value_error(self):
        """create_seed raises ValueError when normalised text already exists."""
        from app.services.seed_service import create_seed

        db = self._make_db()
        fake_existing = MagicMock()

        with patch(
            "app.services.seed_service.get_seed_profile_by_normalised",
            new=AsyncMock(return_value=fake_existing),
        ):
            with pytest.raises(ValueError, match="already exists"):
                await create_seed(db, **self._seed_kwargs())

    @pytest.mark.asyncio
    async def test_new_seed_has_seed_text_normalised_populated(self):
        """create_seed stores the normalised text on the returned profile."""
        from app.services.seed_service import create_seed

        db = self._make_db()
        fake_profile = MagicMock()
        fake_profile.seed_text = "Drug Sale"
        fake_profile.seed_text_normalised = "drug sale"
        fake_profile.id = 1

        with patch(
            "app.services.seed_service.get_seed_profile_by_normalised",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.seed_service.create_seed_profile",
            new=AsyncMock(return_value=fake_profile),
        ), patch(
            "app.services.seed_service._persist_variants",
            new=AsyncMock(return_value=None),
        ):
            result = await create_seed(db, **self._seed_kwargs("Drug Sale"))

        assert result.seed_text_normalised == "drug sale"

    @pytest.mark.asyncio
    async def test_create_seed_calls_persist_variants(self):
        """create_seed always calls _persist_variants to auto-generate variants."""
        from app.services.seed_service import create_seed

        db = self._make_db()
        fake_profile = MagicMock()
        fake_profile.seed_text = "drug sale"
        fake_profile.seed_text_normalised = "drug sale"
        fake_profile.id = 1

        with patch(
            "app.services.seed_service.get_seed_profile_by_normalised",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.seed_service.create_seed_profile",
            new=AsyncMock(return_value=fake_profile),
        ), patch(
            "app.services.seed_service._persist_variants",
            new=AsyncMock(return_value=None),
        ) as mock_persist:
            await create_seed(db, **self._seed_kwargs())

        mock_persist.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_seed_returns_profile_object(self):
        """create_seed returns the SeedProfile object from create_seed_profile."""
        from app.services.seed_service import create_seed

        db = self._make_db()
        fake_profile = MagicMock()
        fake_profile.seed_text = "drug sale"
        fake_profile.seed_text_normalised = "drug sale"
        fake_profile.id = 42

        with patch(
            "app.services.seed_service.get_seed_profile_by_normalised",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.seed_service.create_seed_profile",
            new=AsyncMock(return_value=fake_profile),
        ), patch(
            "app.services.seed_service._persist_variants",
            new=AsyncMock(return_value=None),
        ):
            result = await create_seed(db, **self._seed_kwargs())

        assert result is fake_profile
        assert result.id == 42

    @pytest.mark.asyncio
    async def test_duplicate_check_uses_normalised_form(self):
        """Duplicate detection is performed on the normalised seed text."""
        from app.services.seed_service import create_seed

        db = self._make_db()

        captured_normalised: list[str] = []

        async def fake_get_by_normalised(db_session, normalised_text):
            captured_normalised.append(normalised_text)
            return None  # No duplicate

        fake_profile = MagicMock()
        fake_profile.seed_text = "DRUG SALE"
        fake_profile.seed_text_normalised = "drug sale"
        fake_profile.id = 7

        with patch(
            "app.services.seed_service.get_seed_profile_by_normalised",
            new=fake_get_by_normalised,
        ), patch(
            "app.services.seed_service.create_seed_profile",
            new=AsyncMock(return_value=fake_profile),
        ), patch(
            "app.services.seed_service._persist_variants",
            new=AsyncMock(return_value=None),
        ):
            await create_seed(db, **self._seed_kwargs("DRUG SALE"))

        # The normalised form (lowercase, stripped) must be passed to duplicate check
        assert captured_normalised == ["drug sale"]
