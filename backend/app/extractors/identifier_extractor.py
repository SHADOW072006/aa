"""
Identifier extractor — pulls actionable contact and payment identifiers
from raw message text, plus privacy masking helpers.

Extracted types
---------------
phone       Indian / international phone numbers (incl. spaced & emoji digits)
upi         UPI IDs (allow-listed PSP/bank suffixes only; never email domains)
handle      Telegram / Instagram / Twitter handles (@username, t.me/<slug>)
ifsc        IFSC bank branch codes
bank_card   Payment card numbers (Luhn-validated, 13-19 digits)
imei        Device IMEI (15 digits, Luhn-validated)
location    Indian cities mentioned with delivery/supply prepositions
wallet_btc  Bitcoin addresses (P2PKH, P2SH, Bech32)
wallet_eth  Ethereum addresses
wallet_usdt USDT (TRC-20 / ERC-20)
email       Email addresses
url         Suspicious URLs / t.me links
"""

from __future__ import annotations

import re
from typing import List, NamedTuple, Set

import phonenumbers
from phonenumbers import PhoneNumberMatcher


class ExtractedIdentifier(NamedTuple):
    type: str
    value: str
    normalised: str


_KNOWN_UPI_HANDLES = (
    "oksbi|okicici|okaxis|okhdfc|okbizaxis|ybl|apl|ibl|paytm|upi|airtel|jio|"
    "kotak|sbi|icici|axis|hdfc|federal|idbi|rbl|indus|indusind|pnb|bob|boi|"
    "canara|union|ubi|syndicate|allahabad|vijaya|dena|obc|andhra|"
    "corporation|central|indian|mahb|iob|post|waicici|wahdfcbank|wasbi|"
    "ikwik|jupiteraxis|pingpay|fbl|axl|naviaxis|aubank|payzapp|freecharge|"
    "mobikwik|navi|slice|kbl|csb|kvb|jsb|psb|vijb|okhdfcbank|okicicibank|okbizaxis|aupi|ibl|apl"
)

# UPI: suffix must be a known PSP/bank handle. The previous catch-all
# fallback ("@<anything>") misclassified Telegram bot links ("ban@bot",
# "goo@gle") as UPI IDs — precision beats recall here.
_UPI_RE = re.compile(
    rf"\b[a-zA-Z0-9.\-_+]{{2,}}@(?:{_KNOWN_UPI_HANDLES})\b",
    re.IGNORECASE,
)

# Handle must NOT be preceded by word/dot/plus/hyphen characters (prevents matching inside email/UPI).
# Starts with a letter (Telegram/Instagram rule), may contain dots, must not end on a dot.
_HANDLE_RE = re.compile(
    r"(?<![a-zA-Z0-9._%+\-])@([a-zA-Z](?:[a-zA-Z0-9_.\-]{3,30}[a-zA-Z0-9_])?)(?![a-zA-Z0-9_])"
)

# Identifier types that identify an actor (a person or channel). Only these
# create entity links and connect channels; url/location are evidence, not identity.
CONTACT_TYPES = frozenset({
    "phone", "upi", "handle", "email", "ifsc", "bank_card", "imei",
    "wallet_btc", "wallet_eth", "wallet_usdt", "bank_account", "site",
})


def is_contact_identifier(ident_type: str) -> bool:
    return ident_type in CONTACT_TYPES

_BTC_RE = re.compile(r"\b(?:bc1[ac-hj-np-z02-9]{6,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
_ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_TRON_RE = re.compile(r"\bT[a-zA-Z0-9]{33}\b")
_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")
_URL_RE = re.compile(r"(?:https?://|t\.me/|telegram\.me/)([^\s\"'<>]{3,100})", re.IGNORECASE)

# Spaced/formatted Indian phone numbers (e.g. +91 98765 43210, 98765-43210, 9 8 7 6 5 4 3 2 1 0)
_SPACED_IN_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+91[\s\-]*|91[\s\-]*|0[\s\-]*)?(?:[6-9](?:[\s\-]*\d){9})(?!\d)"
)

_EMOJI_DIGIT_RE = re.compile(r"([0-9])\ufe0f?\u20e3")

# Devanagari digits (७४१४० २९९५१) -> ASCII before any digit matching
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Phones spelled out in words ("nine seven eight three one zero four four seven two")
_WORD_NUM = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
             "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_NUM_WORD = "|".join(_WORD_NUM)
_WORD_PHONE_RE = re.compile(rf"\b(?:{_NUM_WORD})(?:[\s\-]+(?:{_NUM_WORD})){{9}}\b")

# IFSC: 4-letter bank code + 0 + 6 alphanumeric (officially uppercase, often typed lowercase)
_IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", re.IGNORECASE)

# Bank account numbers: explicit context ("current a/c 5020...", "account no 501...")
_BANK_ACCOUNT_CTX_RE = re.compile(
    r"(?:a/c|account|acc|ac|khata)\s*(?:no\.?|number|#)?\s*[:=\-]?\s*(?P<num>\d{9,18})",
    re.IGNORECASE,
)
_BANK_ACCOUNT_PARTIAL_RE = re.compile(
    r"(?:ending|a/c|account|acc|ac)\s*(?:no\.?|number)?\s*(?:\.\.+|\*+|x+)(?P<num>\d{5,10})\b",
    re.IGNORECASE,
)
_BANK_ACCOUNT_BARE_RE = re.compile(r"(?<!\d)(\d{11,18})(?!\d)")

# Bare domains ("pvcprint-hub.in", "allservices247.in") — emails are excluded
# by span overlap and t.me/telegram.me are handled as links, not sites.
_SITE_RE = re.compile(
    r"\b(?:[a-z0-9][a-z0-9\-]*\.)+(?:com|in|net|org|xyz|online|site|shop|store|co|io|info|biz|club|app|live)\b",
    re.IGNORECASE,
)

# Card / IMEI candidates: 13-19 digits, optionally space/dash grouped
_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")

# t.me / telegram.me public channel slugs (t.me/s/<slug> preview links too;
# '+invite' links carry no username and are not matched)
_TG_LINK_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_TG_RESERVED_SLUGS = {"joinchat", "addstickers", "proxy", "socks", "bg", "share", "iv"}

# Locations: any gazetteer mention counts as evidence (cities are not contact
# identifiers, so over-matching costs nothing downstream).
_LOCATION_MAX_TOKENS = 4  # longest gazetteer entry: "dadra and nagar haveli"
_CITY_ACRONYMS = {"ncr", "up", "mp", "ap", "ts", "tn"}
_CITY_ACRONYMS = {"ncr", "up", "mp", "ap", "ts", "tn"}

# States, union territories and major cities.
_KNOWN_CITIES = frozenset({
    "agartala", "agra", "ahmedabad", "aizawl", "ajmer", "akola", "aligarh", "allahabad",
    "alwar", "ambala", "amravati", "amritsar", "anand", "anantnag", "andaman and nicobar",
    "andhra pradesh", "ap", "ara", "arunachal pradesh", "asansol", "assam", "aurangabad",
    "ballari", "bangalore", "baramulla", "bareilly", "bathinda", "begusarai", "belgaum",
    "belgavi", "bellary", "bengaluru", "bhagalpur", "bharuch", "bhavnagar", "bhilai",
    "bhilwara", "bhopal", "bhubaneswar", "bhuntar", "bihar", "bikaner", "bilaspur", "bokaro",
    "buxar", "chandigarh", "chapra", "chennai", "chhattisgarh", "cochin", "coimbatore",
    "cuttack", "dadra and nagar haveli", "daman", "darbhanga", "davangere", "dehradun",
    "delhi", "delhi ncr", "dhanbad", "dharamshala", "dharwad", "dhule", "dibrugarh",
    "dombivli", "durg", "durgapur", "erode", "faridabad", "firozabad", "gandhinagar",
    "gangtok", "ghaziabad", "goa", "gorakhpur", "greater noida", "gujarat", "gulbarga",
    "guntur", "gurgaon", "gurugram", "guwahati", "gwalior", "hajipur", "haldwani", "haridwar",
    "haryana", "hazaribagh", "himachal pradesh", "hisar", "howrah", "hubballi", "hubli",
    "hyderabad", "imphal", "indore", "itanagar", "jabalpur", "jaipur", "jalandhar", "jalgaon",
    "jammu", "jammu and kashmir", "jamnagar", "jamshedpur", "jhansi", "jharkhand", "jodhpur",
    "sri ganganagar", "hanumangarh", "bharatpur", "dholpur", "pushkar", "sikar",
    "junagadh", "kakinada", "kalaburagi", "kalyan", "kanpur", "karimnagar", "karnal",
    "karnataka", "katra", "kavaratti", "kerala", "khammam", "kharagpur", "kochi", "kohima",
    "kolhapur", "kolkata", "kota", "kullu", "kurnool", "ladakh", "lakshadweep", "latur",
    "lucknow", "ludhiana", "madhya pradesh", "madurai", "maharashtra", "malda", "malegaon",
    "manali", "mangalore", "mangaluru", "manipur", "mathura", "meerut", "meghalaya",
    "mirzapur", "mizoram", "mohali", "moradabad", "motihari", "mp", "mumbai", "muzaffarpur",
    "mysore", "mysuru", "nagaland", "nagpur", "nanded", "nashik", "navi mumbai", "ncr",
    "nellore", "new delhi", "nizamabad", "noida", "odisha", "orissa", "palghar", "panaji",
    "panchkula", "panipat", "panvel", "patiala", "patna", "pimpri chinchwad", "pondicherry",
    "port blair", "prayagraj", "puducherry", "pune", "punjab", "purnia", "raipur",
    "rajahmundry", "rajasthan", "rajkot", "ranchi", "rewa", "rewari", "rohtak", "roorkee",
    "rourkela", "rudrapur", "sagar", "saharanpur", "saharsa", "salem", "salt lake",
    "samastipur", "sambalpur", "sangli", "sasaram", "satna", "secunderabad", "shillong",
    "shimla", "sikkim", "siliguri", "silvassa", "sirsa", "sitamarhi", "siwan", "solan",
    "solapur", "sonipat", "srinagar", "sultanpur", "surat", "tamil nadu", "telangana", "thane",
    "thanjavur", "tiruchirappalli", "tirunelveli", "tirupati", "tiruppur", "tn", "trichy",
    "tripura", "ts", "udaipur", "udhampur", "ujjain", "up", "uttar pradesh", "uttarakhand",
    "vadodara", "varanasi", "vasai", "vellore", "vijayawada", "virar", "visakhapatnam",
    "vizag", "warangal", "west bengal", "yamunanagar",
})


def _luhn_ok(digits: str) -> bool:
    """Standard Luhn checksum (payment cards and IMEI both use it)."""
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _normalise_emoji_and_spaced_digits(text: str) -> str:
    """Convert keycap emoji digits (e.g. 9️⃣) into ASCII digits for phone matching."""
    return _EMOJI_DIGIT_RE.sub(r"\1", text)


def _normalise_phone(raw: str) -> Optional[str]:
    """
    Canonicalise a candidate Indian mobile number to E.164, or None when the
    digits don't form a plausible 10-digit Indian mobile. Never invents a
    prefix: "098765 43210" and "98765 43210" and "+91 98765 43210" all land
    on "+919876543210" (so the library matcher and the fallback dedupe).
    """
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return None


def _normalise_handle(raw: str) -> str:
    return raw.lower().lstrip("@")


def _display_city(span: str) -> str:
    """"delhi ncr" -> "Delhi NCR", "uttar pradesh" -> "Uttar Pradesh"."""
    return " ".join(t.upper() if t in _CITY_ACRONYMS else t.capitalize() for t in span.split())


def mask_identifier(ident_type: str, value: str) -> str:
    """Mask identifier values for default list/aggregate views (e.g. 98xxxxxx10, ab***@upi)."""
    if not value:
        return value
    t = ident_type.lower()
    if t == "phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 6:
            return f"{digits[:2]}{'x' * (len(digits) - 4)}{digits[-2:]}"
        return "x" * len(value)
    if t in ("upi", "email") and "@" in value:
        local, dom = value.split("@", 1)
        prefix = local[:2] if len(local) >= 2 else local[:1]
        return f"{prefix}***@{dom}"
    if t in ("ifsc", "location", "site"):
        return value
    if t == "bank_account":
        digits = re.sub(r"\D", "", value)
        return f"xxxx{digits[-4:]}" if len(digits) >= 4 else "***"
    if t == "bank_card":
        digits = re.sub(r"\D", "", value)
        return f"****{digits[-4:]}" if len(digits) >= 4 else "***"
    if t == "handle":
        clean = value.lstrip("@")
        prefix = clean[:2] if len(clean) >= 2 else clean[:1]
        return f"@{prefix}***"
    if t.startswith("wallet_") and len(value) > 10:
        return f"{value[:6]}...{value[-4:]}"
    if len(value) > 6:
        return f"{value[:3]}***{value[-2:]}"
    return "***"


def extract(text: str) -> List[ExtractedIdentifier]:
    results: List[ExtractedIdentifier] = []
    seen: Set[str] = set()

    def _add(typ: str, value: str, normalised: str) -> None:
        key = f"{typ}::{normalised}"
        if key not in seen:
            seen.add(key)
            results.append(ExtractedIdentifier(type=typ, value=value, normalised=normalised))

    prepped = _normalise_emoji_and_spaced_digits(text)
    prepped = prepped.translate(_DEVANAGARI_DIGITS)

    phone_spans: List[tuple] = []

    # ── Phone numbers via phonenumbers library ────────────────────────────────
    for match in PhoneNumberMatcher(prepped, "IN"):
        norm = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
        phone_spans.append((match.start, match.end))
        _add("phone", match.raw_string, norm)

    # ── Fallback regex for spaced/emoji Indian mobiles ──────────────────────
    for m in _SPACED_IN_PHONE_RE.finditer(prepped):
        norm = _normalise_phone(m.group())
        if norm:
            phone_spans.append(m.span())
            _add("phone", m.group().strip(), norm)

    # ── Phones spelled out in words ("nine seven eight three ... two") ────────
    for m in _WORD_PHONE_RE.finditer(prepped.lower()):
        digits = "".join(_WORD_NUM[w] for w in re.split(r"[\s\-]+", m.group()))
        if len(digits) == 10 and digits[0] in "6789":
            phone_spans.append(m.span())
            _add("phone", m.group().strip(), "+91" + digits)

    # ── Emails first (so UPI & handle never match inside an email) ────────────
    email_spans: List[tuple[int, int]] = []
    for m in _EMAIL_RE.finditer(text):
        email_spans.append(m.span())
        _add("email", m.group(), m.group().lower())

    def _in_spans(start: int, end: int, spans: List[tuple[int, int]]) -> bool:
        return any(s <= start and end <= e for s, e in spans)

    # ── UPI IDs (never match inside an email domain) ──────────────────────────
    upi_spans: List[tuple[int, int]] = []
    for m in _UPI_RE.finditer(text):
        if _in_spans(m.start(), m.end(), email_spans):
            continue
        val = m.group()
        upi_spans.append(m.span())
        _add("upi", val, val.lower().strip())

    # ── Telegram / social handles (never inside email or UPI) ─────────────────
    for m in _HANDLE_RE.finditer(text):
        if _in_spans(m.start(), m.end(), email_spans) or _in_spans(m.start(), m.end(), upi_spans):
            continue
        handle = m.group(1)
        if handle.lower() not in {"gmail", "yahoo", "hotmail", "outlook", "icloud"}:
            _add("handle", m.group(0), _normalise_handle(handle))

    # ── Crypto wallets ────────────────────────────────────────────────────────
    for m in _BTC_RE.finditer(text):
        _add("wallet_btc", m.group(), m.group().lower())
    for m in _ETH_RE.finditer(text):
        _add("wallet_eth", m.group(), m.group().lower())
    for m in _TRON_RE.finditer(text):
        if len(m.group()) == 34:
            # case-insensitive identity: the same TRON address typed in any
            # casing must land on one node in the entity graph
            _add("wallet_usdt", m.group(), m.group().lower())

    # ── IFSC codes ────────────────────────────────────────────────────────────
    for m in _IFSC_RE.finditer(text):
        _add("ifsc", m.group(), m.group().upper())

    # ── Bank cards (Luhn-validated) and IMEI (15-digit, Luhn-validated) ──────
    card_spans: List[tuple] = []
    for m in _CARD_CANDIDATE_RE.finditer(prepped):
        digits = re.sub(r"\D", "", m.group())
        n = len(digits)
        if n < 13 or n > 19 or not _luhn_ok(digits):
            continue
        card_spans.append(m.span())
        if n == 15:
            _add("imei", digits, digits)
        else:
            _add("bank_card", m.group().strip(), digits)

    # ── Bank account numbers (context-gated + bare long runs) ─────────────────
    def _not_phone_or_card(s: int, e: int) -> bool:
        return not _in_spans(s, e, phone_spans) and not _in_spans(s, e, card_spans)

    for m in _BANK_ACCOUNT_CTX_RE.finditer(prepped):
        digits = m.group("num")
        s, e = m.span("num")
        if len(digits) >= 9 and _not_phone_or_card(s, e):
            _add("bank_account", digits, digits)
    for m in _BANK_ACCOUNT_BARE_RE.finditer(prepped):
        digits = m.group(1)
        if _not_phone_or_card(*m.span(1)) and not _luhn_ok(digits):
            _add("bank_account", digits, digits)

    # ── Sites / bare domains ──────────────────────────────────────────────────
    for m in _SITE_RE.finditer(text):
        if _in_spans(m.start(), m.end(), email_spans):
            continue
        val = m.group().lower()
        if val in {"t.me", "telegram.me"} or val.endswith(".me"):
            continue
        _add("site", m.group(), val)

    # ── Locations: any gazetteer mention (longest match wins) ────────────────
    tokens = [t for t in re.split(r"[\s,./();:!?'\"]+", text.lower()) if t]
    i = 0
    while i < len(tokens):
        span = None
        for n in range(min(_LOCATION_MAX_TOKENS, len(tokens) - i), 0, -1):
            candidate = " ".join(tokens[i:i + n])
            if candidate in _KNOWN_CITIES:
                span = candidate
                break
        if span:
            _add("location", _display_city(span), span)
            i += len(span.split())
        else:
            i += 1

    # ── URLs / t.me links ─────────────────────────────────────────────────────
    for m in _URL_RE.finditer(text):
        raw = m.group()
        _add("url", raw, raw.lower())

    # ── Public Telegram channel slugs (t.me/<username>) as handles ───────────
    for m in _TG_LINK_RE.finditer(text):
        slug = m.group(1)
        if slug.lower() not in _TG_RESERVED_SLUGS:
            _add("handle", slug, slug.lower())

    return results
