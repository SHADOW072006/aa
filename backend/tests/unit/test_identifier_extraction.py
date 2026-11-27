"""
Identifier extraction hardening: precision (no junk UPI/handles), canonical
phone identities, new identifier types, and the contact-type linking rule.
All values below are synthetic placeholders.
"""
from __future__ import annotations

from app.extractors.identifier_extractor import (
    CONTACT_TYPES,
    extract,
    is_contact_identifier,
)


def _of(text: str, typ: str) -> set[str]:
    return {i.normalised for i in extract(text) if i.type == typ}


def _types(text: str) -> set[str]:
    return {i.type for i in extract(text)}


# ── UPI ──────────────────────────────────────────────────────────────────────

def test_upi_requires_known_psp_or_bank_suffix_and_keeps_full_value():
    assert _of("pay to rahul.sharma@okaxis or shop99@ybl", "upi") == {"rahul.sharma@okaxis", "shop99@ybl"}
    assert _of("UPI: demo.seller@paytm", "upi") == {"demo.seller@paytm"}


def test_upi_rejects_bot_links_and_lookalikes():
    for text in ("use /cancel@mentionbot to stop", "goo@gle it", "price@1500.00", "start@missrose_bot?start=abc"):
        assert _of(text, "upi") == set(), text


def test_plain_words_never_become_upi_ids():
    # Regression guard: the suffix alternation must stay grouped.
    for text in ("pay via UPI only", "SBI account holder", "recharge with Jio", "IFSC SBIN0001234 here"):
        assert _of(text, "upi") == set(), text


# ── Phones ───────────────────────────────────────────────────────────────────

def test_phone_formats_collapse_to_one_identity():
    for text in ("call +91 98765 43210", "whatsapp 98765-43210", "call 098765 43210", "9876543210"):
        assert _of(text, "phone") == {"+919876543210"}, text


def test_landline_keeps_a_single_library_normalised_identity():
    # A landline is a real contact number; it must land on exactly one E.164 value.
    assert _of("landline 011 2345 6789", "phone") == {"+911123456789"}


# ── Handles / t.me links ─────────────────────────────────────────────────────

def test_handle_allows_dots_and_requires_leading_letter():
    assert _of("dm @seller.x now", "handle") == {"seller.x"}
    assert _of("dm @drugplug_91", "handle") == {"drugplug_91"}
    assert _of("Price@1500 only", "handle") == set()


def test_telegram_public_links_resolve_to_handles():
    text = "join https://t.me/sellerx_official or t.me/s/demo_channel_1"
    assert _of(text, "handle") == {"sellerx_official", "demo_channel_1"}
    # invite hashes and reserved paths carry no username
    assert _of("t.me/+AbCdEf123 and t.me/joinchat/xyz", "handle") == set()


def test_mention_and_link_for_same_username_dedupe():
    assert _of("dm @sellerx_official or join t.me/sellerx_official", "handle") == {"sellerx_official"}


def test_email_never_yields_handle_or_upi():
    types = _types("mail fake.seller@example.com")
    assert types == {"email"}


# ── IFSC / cards / IMEI ──────────────────────────────────────────────────────

def test_ifsc_is_case_insensitive_and_normalised_uppercase():
    assert _of("IFSC sbin0001234 branch", "ifsc") == {"SBIN0001234"}


def test_card_requires_luhn_checksum():
    # 4242... is the published industry-wide test PAN, not a real card.
    assert _of("card 4242 4242 4242 4242 cvv 123", "bank_card") == {"4242424242424242"}
    assert _of("card 4242 4242 4242 4243 cvv 123", "bank_card") == set()


def test_imei_is_luhn_validated_15_digits():
    assert _of("IMEI 356938035643809", "imei") == {"356938035643809"}
    assert _of("IMEI 356938035643808", "imei") == set()


# ── Locations ────────────────────────────────────────────────────────────────

def test_locations_need_a_delivery_cue_and_match_the_gazetteer():
    text = "Home delivery in Delhi NCR, Mumbai and Pune. COD available."
    assert _of(text, "location") == {"delhi ncr", "mumbai", "pune"}
    values = [i.value for i in extract(text) if i.type == "location"]
    assert values == ["Delhi NCR", "Mumbai", "Pune"]


def test_locations_are_extracted_from_gazetteer_and_ignore_unknown_cities():
    assert _of("I love Mumbai city life", "location") == {"mumbai"}
    assert _of("delivery in Springfield", "location") == set()
    assert _of("shipping across uttar pradesh", "location") == {"uttar pradesh"}


# ── Linking rule ─────────────────────────────────────────────────────────────

def test_only_actor_identifiers_are_linkable():
    assert is_contact_identifier("phone") and is_contact_identifier("upi") and is_contact_identifier("handle")
    assert "url" not in CONTACT_TYPES and "location" not in CONTACT_TYPES
