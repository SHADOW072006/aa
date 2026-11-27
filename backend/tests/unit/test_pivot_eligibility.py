"""
Unit tests for app/services/pivot_service.py::extract_pivot_candidates

Requirements: 4.1, 4.2, 4.3
"""

from __future__ import annotations

import pytest

from app.services.pivot_service import extract_pivot_candidates

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _types(results: list[dict]) -> list[str]:
    return [r["candidate_type"] for r in results]


def _values(results: list[dict]) -> list[str]:
    return [r["candidate_value"] for r in results]


def _find(results: list[dict], ctype: str) -> list[str]:
    return [r["candidate_value"] for r in results if r["candidate_type"] == ctype]


# ---------------------------------------------------------------------------
# Phone extraction  (Requirement 4.1)
# ---------------------------------------------------------------------------

class TestPhoneExtraction:
    def test_international_phone_e164(self):
        """'+79001234567' is extracted as a phone."""
        results = extract_pivot_candidates("+79001234567", "chan")
        assert "phone" in _types(results)
        assert "+79001234567" in _find(results, "phone")

    def test_uk_style_phone_no_plus(self):
        """'07911123456' (10 digits, no plus) is extracted as a phone."""
        results = extract_pivot_candidates("07911123456", "chan")
        assert "phone" in _types(results)
        assert "07911123456" in _find(results, "phone")

    def test_short_number_not_extracted(self):
        """'123' (3 digits, < 7) must NOT be extracted."""
        results = extract_pivot_candidates("123", "chan")
        assert "phone" not in _types(results)

    def test_six_digit_number_not_extracted(self):
        """A 6-digit number is below the 7-digit threshold and must not appear."""
        results = extract_pivot_candidates("654321", "chan")
        assert "phone" not in _types(results)

    def test_phone_embedded_in_text(self):
        """Phone surrounded by prose is still extracted."""
        results = extract_pivot_candidates("call +1234567890 now", "chan")
        assert "+1234567890" in _find(results, "phone")

    def test_phone_at_end_of_sentence(self):
        """Phone appearing at end of text is captured."""
        results = extract_pivot_candidates("reach me at +79009876543", "chan")
        assert "+79009876543" in _find(results, "phone")


# ---------------------------------------------------------------------------
# Telegram handle extraction  (Requirement 4.2)
# ---------------------------------------------------------------------------

class TestTelegramHandle:
    def test_simple_handle(self):
        """'@drugdealer' → type='telegram_handle', value='drugdealer' (no @)."""
        results = extract_pivot_candidates("@drugdealer", "chan")
        assert "telegram_handle" in _types(results)
        assert "drugdealer" in _find(results, "telegram_handle")

    def test_handle_value_strips_at_sign(self):
        """The returned value must NOT include the leading '@'."""
        results = extract_pivot_candidates("@testuser99", "chan")
        values = _find(results, "telegram_handle")
        assert all(not v.startswith("@") for v in values)

    def test_too_short_handle_not_extracted(self):
        """'@ab' is only 2 chars (excluding @) which is < 4, so it is skipped."""
        results = extract_pivot_candidates("@ab", "chan")
        assert "ab" not in _find(results, "telegram_handle")

    def test_handle_with_underscores_and_digits(self):
        """'@valid_user123' contains underscores and digits, should be extracted."""
        results = extract_pivot_candidates("@valid_user123", "chan")
        assert "valid_user123" in _find(results, "telegram_handle")

    def test_handle_in_prose(self):
        """Handle embedded mid-sentence is still captured."""
        results = extract_pivot_candidates("send DM to @mycontact for info", "chan")
        assert "mycontact" in _find(results, "telegram_handle")


# ---------------------------------------------------------------------------
# Telegram link extraction  (Requirement 4.2)
# ---------------------------------------------------------------------------

class TestTelegramLink:
    def test_bare_tme_link(self):
        """'t.me/channel123' → type='telegram_link', value='channel123'."""
        results = extract_pivot_candidates("t.me/channel123", "chan")
        assert "telegram_link" in _types(results)
        assert "channel123" in _find(results, "telegram_link")

    def test_https_tme_link(self):
        """'https://t.me/group' is extracted; value is 'group'."""
        results = extract_pivot_candidates("https://t.me/group", "chan")
        assert "group" in _find(results, "telegram_link")

    def test_tme_link_in_sentence(self):
        """t.me link surrounded by text is still captured."""
        results = extract_pivot_candidates("join us at t.me/secret_chat today", "chan")
        assert "secret_chat" in _find(results, "telegram_link")


# ---------------------------------------------------------------------------
# Email extraction  (Requirement 4.3)
# ---------------------------------------------------------------------------

class TestEmailExtraction:
    def test_simple_email(self):
        """'user@example.com' → type='email', value='user@example.com'."""
        results = extract_pivot_candidates("user@example.com", "chan")
        assert "email" in _types(results)
        assert "user@example.com" in _find(results, "email")

    def test_non_email_string_not_extracted(self):
        """'not-an-email' contains no '@domain.tld' pattern and must be skipped."""
        results = extract_pivot_candidates("not-an-email", "chan")
        assert "email" not in _types(results)

    def test_email_in_prose(self):
        """Email inside a sentence is captured."""
        results = extract_pivot_candidates("contact us at support@domain.org for help", "chan")
        assert "support@domain.org" in _find(results, "email")


# ---------------------------------------------------------------------------
# URL domain extraction
# ---------------------------------------------------------------------------

class TestUrlDomain:
    def test_https_url_yields_domain(self):
        """'https://example.com/path' → type='url_domain', value='example.com'."""
        results = extract_pivot_candidates("https://example.com/path", "chan")
        assert "url_domain" in _types(results)
        assert "example.com" in _find(results, "url_domain")

    def test_http_url_yields_domain(self):
        """Plain http:// URL also produces a url_domain entry."""
        results = extract_pivot_candidates("http://shop.onion.com/buy", "chan")
        assert "shop.onion.com" in _find(results, "url_domain")


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_duplicate_handle_appears_once(self):
        """Same handle repeated twice → only one result for that handle."""
        text = "message @dupuser and also @dupuser"
        results = extract_pivot_candidates(text, "chan")
        handles = _find(results, "telegram_handle")
        assert handles.count("dupuser") == 1

    def test_duplicate_phone_appears_once(self):
        """Same phone twice → extracted once only."""
        text = "+79001111111 and +79001111111"
        results = extract_pivot_candidates(text, "chan")
        phones = _find(results, "phone")
        assert phones.count("+79001111111") == 1


# ---------------------------------------------------------------------------
# Multiple types in one text
# ---------------------------------------------------------------------------

class TestMultipleTypes:
    def test_handle_link_and_phone_all_extracted(self):
        """'contact @user or t.me/chan or +79001234567' → all three found."""
        text = "contact @userhandle or t.me/chanslug or +79001234567"
        results = extract_pivot_candidates(text, "src")
        assert "userhandle" in _find(results, "telegram_handle")
        assert "chanslug" in _find(results, "telegram_link")
        assert "+79001234567" in _find(results, "phone")

    def test_email_url_and_phone_together(self):
        """Email, URL, and phone coexist in one extraction pass."""
        text = "admin@example.com visit https://example.com call +12025550100"
        results = extract_pivot_candidates(text, "src")
        assert "admin@example.com" in _find(results, "email")
        assert "example.com" in _find(results, "url_domain")
        assert "+12025550100" in _find(results, "phone")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string_returns_empty_list(self):
        """Empty text → []."""
        assert extract_pivot_candidates("", "chan") == []

    def test_whitespace_only_returns_empty_list(self):
        """Whitespace-only text → []."""
        assert extract_pivot_candidates("   \n\t  ", "chan") == []

    def test_channel_username_param_does_not_affect_output(self):
        """The channel_username argument is ignored during extraction."""
        text = "@testhandle"
        r1 = extract_pivot_candidates(text, "channelA")
        r2 = extract_pivot_candidates(text, "channelB")
        assert r1 == r2
