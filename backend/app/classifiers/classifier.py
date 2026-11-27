"""
Two-stage intent-aware, explainable illegal-sale classifier (intent_v3).

Assesses before alerting:
- Category anchor terms (from core illegal-trade lexicons)
- Offer/sale/supply/rent/recruitment language
- Payment/contact/delivery/call-to-action language
- Identifier/contact presence (phone, UPI, handle, wallet, email, URL)
- Negative context (news, reporting, prevention, denial, warnings)

Rules:
- A category keyword alone cannot produce HIGH (capped at SCORE_KEYWORD_ONLY_CAP).
- Emoji-only is non-actionable (0.0 / LOW).
- Ambiguous words require a category anchor PLUS sale/recruitment/CTA context.
- Under default profile="illegal_trade", investment/colour-trading/gambling/scam
  terms are excluded so they are not mislabelled as core illegal-trade alerts.
- ML scoring is disabled by default (USE_ML_SCORING=False) until validated against
  sufficient reviewed real records; when enabled, uses a symmetric weighted blend
  so ML can both raise and lower the score.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import emoji as emoji_lib
import joblib

from app.classifiers.lexicon_loader import LexiconStore, get_lexicon_store
from app.core.config import settings
from app.extractors.identifier_extractor import extract as extract_identifiers
from app.extractors.normaliser import normalise

logger = logging.getLogger(__name__)

# ── Ambiguous terms: need a strong category anchor in the same post ──────────
# Homonyms and everyday words. They never count on their own.
_AMBIGUOUS_TERMS: Set[str] = {
    "brown", "white", "ice", "rock", "crack", "glass", "horse",
    "snow", "speed", "pot", "bud", "tabs", "bars", "plug", "dealer",
    "dm for price", "dm to order", "ping me", "top quality", "quality stuff", "stuff available",
    "guaranteed delivery", "stealth shipping", "discreet delivery",
    "usdt", "referral bonus", "airdrop", "presale", "token launch",
    "moonshot", "daily income", "daily earning", "online job", "part time job",
    "no risk", "copy trading", "deposit karo", "recharge karo",
    # "Royal Enfield Bullet 350 for sale" — the classic arms false positive
    "bullet",
}

# ── Weak domain objects: legitimate marketing uses the same words ─────────────
# Count only when a real sale/rent/recruitment verb AND a contact identifier are
# both present (a criminal sale ad always carries a way to reach the seller).
_WEAK_OBJECT_TERMS: Set[str] = {
    # banking / cards / SIM
    "net banking", "netbanking", "netbanking available", "net banking available", "banking kit",
    "passbook", "cheque book", "upi id", "scan copy", "account available", "zero balance account",
    "paytm account", "phonepe account", "gpay account", "login id password",
    "atm card", "atm cards", "atm card available", "debit card", "credit card", "card for sale",
    "sim card", "sim cards", "sim available", "sim card available",
    "high limit", "vintage account", "vintage accounts", "old account", "current a/c",
    "full kit", "voter id", "savings bank", "aadhaar pan", "hdfc ca", "icici ca", "sbi ca", "axis ca",
    # "goods" slang and weapons named without sale phrasing
    "maal", "माल", "pistol", "revolver", "rifle", "crypto wallet", "btc wallet", "original looking",
    "khilone", "tools", "naya saman", "goli", "pahadi stuff", "special tablets", "md",
}

# Term -> pattern that reveals a benign meaning; the term is then ignored.
_BENIGN_COLLOCATION_RE: Dict[str, str] = {
    "weed": r"weed\s+(?:killer|control|whacker|eater)|herbicide|lawn\s+care|garden(?:ing|er)",
    "hash": r"hash\s+browns|tx(?:n)?[.\s]*hash|transaction\s*hash|block\s?hash|"
            r"hash\s+(?:tag|rate|code|value|key|function|ing)",
    "coke": r"coca\s*cola|pepsi|thums?\s*up|sprite|soft\s*drink|soda|"
            r"(?:can|bottle|pack)\s+of\s+coke|coke\s+(?:zero|light|diet|can|bottle)",
    "grass": r"lemon\s*grass|wheat\s*grass|grass\s*(?:cut|court|fed)|grasshopper",
    "acid": r"acid\s+(?:rain|reflux|base)|amino\s+acid|stomach\s+acid|hyaluronic",
    "crystal": r"crystal\s+(?:clear|palace|water)|salt\s*crystal",
    "smack": r"smack\s+(?:down|talk)",
    "420": r"section\s*420",
    "pills": r"creatine|multivitamin|whey|supplement|vitamin|protein|pre[- ]?workout|"
             r"gym|fitness|diet|pharmacy|medicine\b|medicines",
    "pistol": r"toy|water\s*(?:pistol|gun)|nerf|holi|replica|airsoft|paintball|bgmi|gun\s*skin",
    "revolver": r"toy|water\s*(?:pistol|gun)|nerf|holi|replica|airsoft|paintball|bgmi|gun\s*skin",
    "rifle": r"toy|water\s*(?:pistol|gun)|nerf|holi|replica|airsoft|paintball|bgmi|gun\s*skin",
    "maal": r"protein|whey|creatine|supplement|gym|fitness|diet|vitamin",
    "aadhaar pan": r"se\s+link|link\s+karwa|pan\s+inactive|official\s+notice|uidai|income\s+tax",
}

# Emojis that may carry a flag on their own (with sale/CTA context). Only the
# substance-specific emojis qualify — decoration emojis (🔥🚀💎📱💳🏦) appear in
# thousands of unrelated spam posts and mislabel them (real-data evidence).
_EMOJI_FALLBACK_CATEGORIES = {
    "cannabis", "psilocybin", "mdma", "heroin", "injection_drug", "pills",
}

_ANCHOR_WEIGHT = 0.80

# Sale/rent/recruitment verbs that imply a transaction (generic availability and
# delivery words are intent, but not enough on their own to promote a weak object).
_STRONG_INTENT = (
    r"for\s+sale|sale|on\s+rent|rent|rental|wanted|commission|supplier|supply|stock|"
    r"order\s+now|buy\s+now|selling|sell|chahiye|चाहिए|bikau|kiraye|kiraya|lena\s+hai|dena\s+hai|"
    r"deni\s+hai|len\s+den|बिकाऊ|किराए|सप्लाई|wholesale|bulk\s+(?:order|rate|me)"
)

# ── Intent, CTA/payment, and negative-context patterns ────────────────────────
_SALE_INTENT_RE = re.compile(
    rf"(?<!\w)(?:{_STRONG_INTENT}|available|ready|delivery|deliver|shipping|उपलब्ध)(?!\w)",
    re.IGNORECASE,
)

_STRONG_INTENT_RE = re.compile(rf"(?<!\w)(?:{_STRONG_INTENT})(?!\w)", re.IGNORECASE)

# Buyer-side mule recruitment uses "need < qualifier > account/upi/sim" with
# arbitrary qualifiers in between ("Need India corporate account"). Matches
# count as a strong sale verb for weak-object promotion.
_BUYER_INTENT_RE = re.compile(
    r"need\s+(?:\w+\s+){0,3}(?:accounts?|upi|atm|sim\b|debit\s+card|credit\s+card)",
    re.IGNORECASE,
)

_CTA_PAYMENT_RE = re.compile(
    r"(?<!\w)(?:dm|dm\s+me|inbox|ping|contact|whatsapp|telegram|escrow|cod|"
    r"cash\s+on\s+delivery|upi|usdt|btc|cashout|price|rate|bulk|wholesale|संपर्क)(?!\w)",
    re.IGNORECASE,
)

_NEGATIVE_CONTEXT_RE = re.compile(
    r"(?<!\w)(?:news|breaking|arrested|seized|busted|police|ncb|cyber\s+cell|"
    r"fir|court|chargesheet|awareness|scam\s+alert|beware|warning|alert|"
    r"do\s+not\s+share|never\s+share|avoid|report|report\s+karo|fraud\s+hai|scam\s+hai|"
    r"official\s+notice|se\s+link|link\s+karwa|helpline|1930|1933|manas|"
    r"counselling|hospital|nasha\s+mukt|nasha\s+chhodne|editorial|"
    r"press\s+release|awareness\s+campaign|"
    r"गिरफ्तार|पुलिस|चेतावनी|सावधान|जागरूकता|नशा\s+मुक्त|सूचना|अपराध|गुप्त|छोड़ने|चिकित्सा)(?!\w)",
    re.IGNORECASE,
)

# ── Emoji-pair codes (Pune Police / DEA lists) — consecutive emoji pairs ──────
_EMOJI_COMBOS: Dict[str, Tuple[str, float]] = {
    "❄️👃": ("cocaine", 0.92),
    "👃❄️": ("cocaine", 0.92),
    "🍀😮‍💨": ("cannabis", 0.92),
    "😮‍💨🍀": ("cannabis", 0.92),
    "🍁🍁": ("cannabis", 0.80),
    "🧸🔫": ("arms_sale", 0.92),
    "🔫🧸": ("arms_sale", 0.92),
    "🍃🏔️": ("cannabis", 0.80),
    "🏔️🍃": ("cannabis", 0.80),
    "📶📲": ("sim_sale", 0.88),
    "📲📶": ("sim_sale", 0.88),
}

_ml_pipeline = None

# ── Obfuscation handling (applied in the classifier's text pipeline only) ─────
# leetspeak ("g@nja", "p!st0l", "w33d") and dot-acronyms ("A.T.M", "M.D").
_LEET_MAP = str.maketrans({"@": "a", "0": "o", "!": "i", "$": "s", "3": "e", "5": "s",
                           "1": "i", "7": "t"})
_LEET_CHARS = frozenset("@0!$3 51 7".replace(" ", ""))  # maketrans keys are int code points
_LEET_ACRO_RE = re.compile(r"\b(?:[a-z]\.){2,}[a-z]\b")


def _de_leet(norm_text: str) -> str:
    """De-obfuscate words that mix letters with leet symbols."""
    out = []
    for word in norm_text.split():
        letters = sum(ch.isalpha() for ch in word)
        symbols = sum(ch in _LEET_CHARS for ch in word)
        # handles (@name) and digit-only words stay untouched
        if letters >= 1 and symbols >= 1 and not word.startswith("@"):
            out.append(word.translate(_LEET_MAP))
        else:
            out.append(word)
    text = " ".join(out)
    # "A.T.M" / "P.A.N" -> "atm" / "pan"
    return _LEET_ACRO_RE.sub(lambda m: m.group().replace(".", ""), text)


def _load_ml_model() -> None:
    global _ml_pipeline
    model_path = Path(settings.MODEL_PATH)
    if model_path.exists():
        try:
            _ml_pipeline = joblib.load(model_path)
            logger.info("ML classifier loaded from %s", model_path)
        except Exception as exc:
            logger.warning("Could not load ML model (%s); lexicon-only scoring.", exc)
    else:
        logger.info("No ML model at %s; lexicon-only scoring.", model_path)


_load_ml_model()

CRITICAL_CATEGORIES: Set[str] = {
    "national_breach_cyber", "zero_day_exploit", "ransomware", "critical_infra_cyber",
    "defense_leak", "commercial_narcotics_cartel", "wholesale_drug_trafficking",
    "synthetic_opioids_fentanyl", "military_arms_explosives", "assault_rifles",
    "ied_explosives", "drone_arms_drop", "human_trafficking", "organ_trafficking",
    "csam", "contract_crime", "hitman_supari", "gang_extortion", "digital_arrest",
    "counterfeit_currency_ficn", "large_scale_hawala",
}

HIGH_CATEGORIES: Set[str] = {
    "cybercrime", "phishing_kit", "stealer_log", "carding", "cc_dump",
    "mule_recruitment", "account_sale", "card_sale", "sim_sale", "corporate_mule",
    "arms_sale", "drug_sale", "heroin", "cocaine", "methamphetamine", "mdma",
    "forged_documents", "fake_docs", "extortion", "blackmail", "sextortion",
    "hawala_money_laundering", "smuggling", "theft", "stolen_vehicles",
}

PETTY_CATEGORIES: Set[str] = {
    "gambling_scam", "colour_trading_scam", "task_scam", "task_earn_scam",
    "lottery_scam", "investment_fraud", "petty_prediction", "referral_spam",
    "verified_account", "job_fraud", "pig_butchering",
}


def normalise_text(text: str) -> str:
    """Shared normaliser + leet/acronym de-obfuscation (classifier view)."""
    return _de_leet(normalise(text))


def extract_emojis(text: str) -> List[str]:
    return [token["emoji"] for token in emoji_lib.emoji_list(text)]


def _matches_word_boundary(term: str, norm_text: str) -> bool:
    """Ensure term matches on exact word boundaries so 'ice' does not match 'price'."""
    if re.match(r"^[\w\s\-]+$", term, re.UNICODE):
        pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        return bool(re.search(pattern, norm_text))
    return term in norm_text


def _assess_intent_and_context(text: str, norm_text: str) -> Tuple[float, float, float, List[str]]:
    """
    Assess sale/supply/recruitment intent, contact/identifier presence,
    and negative context (news/awareness/warning).
    Returns (intent_confidence, contact_signal, negative_context_penalty, reason_codes).
    """
    reasons: List[str] = []
    sale_hits = len(_SALE_INTENT_RE.findall(norm_text))
    cta_hits = len(_CTA_PAYMENT_RE.findall(norm_text))

    intent_conf = 0.0
    if sale_hits > 0:
        intent_conf += 0.6
        reasons.append("SALE_OR_RENT_INTENT")
    if cta_hits > 0:
        intent_conf += 0.4
        reasons.append("PAYMENT_OR_CTA_SIGNAL")
    intent_conf = min(intent_conf, 1.0)

    idents = extract_identifiers(text)
    contact_signal = min(len(idents) * 0.5, 1.0) if idents else 0.0
    if contact_signal > 0.0:
        reasons.append("CONTACT_IDENTIFIER_PRESENT")

    neg_hits = len(_NEGATIVE_CONTEXT_RE.findall(norm_text))
    if neg_hits >= 2:
        neg_penalty = min(0.75, settings.SCORE_NEGATIVE_PENALTY + 0.25)
    elif neg_hits == 1:
        neg_penalty = settings.SCORE_NEGATIVE_PENALTY
    else:
        neg_penalty = 0.0
    if neg_penalty > 0.0:
        reasons.append("NEGATIVE_CONTEXT_PENALTY")

    return intent_conf, contact_signal, neg_penalty, reasons


def _emoji_fallback_terms(store: LexiconStore, emojis: List[str], norm: str) -> List[Dict]:
    """
    Turn matched category emojis into pseudo terms (discounted weights).

    Only substance-specific drug emojis qualify (see _EMOJI_FALLBACK_CATEGORIES);
    every other criminal post carries text terms anyway. A benign collocation
    in the text ("creatine", "protein") suppresses the pills emoji.
    """
    terms: List[Dict] = []
    for em in emojis:
        cat, wt, lex = store.emojis[em]
        if cat not in _EMOJI_FALLBACK_CATEGORIES or lex == "scams":
            continue
        benign_re = _BENIGN_COLLOCATION_RE.get(cat)
        if benign_re and re.search(benign_re, norm):
            continue
        terms.append(
            {
                "term": f"emoji:{em}",
                "category": cat,
                "weight": min(0.9, wt * 0.85),
                "lexicon": lex,
                "is_emoji": True,
            }
        )
    return terms


def lexicon_score(
    text: str,
    store: LexiconStore,
    *,
    profile: str = "illegal_trade",
) -> Tuple[float, List[Dict], List[str], str]:
    """
    Returns (category_confidence, matched_terms, matched_categories, severity_tier).
    """
    norm = normalise_text(text)
    matched_terms: List[Dict] = []
    seen: set = set()

    sorted_terms = store.sorted_terms() if hasattr(store, "sorted_terms") else sorted(store.terms.keys(), key=len, reverse=True)
    for term in sorted_terms:
        if term in seen:
            continue
        cat, wt, lex = store.terms[term]
        if profile == "illegal_trade" and (lex == "scams" or cat in PETTY_CATEGORIES):
            continue
        if _matches_word_boundary(term, norm):
            # A benign collocation ("TXN hash", "weed killer", "coca cola")
            # reveals the innocent meaning — skip the term entirely.
            benign_re = _BENIGN_COLLOCATION_RE.get(term)
            if benign_re and re.search(benign_re, norm):
                continue
            matched_terms.append(
                {"term": term, "category": cat, "weight": wt, "lexicon": lex, "is_emoji": False}
            )
            seen.add(term)

    emojis_in_text = extract_emojis(text)
    matched_emojis = [em for em in emojis_in_text if em in store.emojis]
    has_intent_context = bool(_SALE_INTENT_RE.search(norm) or _CTA_PAYMENT_RE.search(norm))

    # Emoji-pair codes (❄️👃 cocaine, 🍀😮‍💨 ganja, 🧸🔫 coded weapons) count as
    # category terms BEFORE the empty-match decision, so an emoji-coded post
    # with no text terms still reaches scoring.
    combo_terms: List[Dict] = []
    for a, b in zip(emojis_in_text, emojis_in_text[1:]):
        combo = _EMOJI_COMBOS.get(f"{a}{b}")
        if combo:
            cat, wt = combo
            combo_terms.append(
                {"term": f"emoji:{a}{b}", "category": cat, "weight": wt,
                 "lexicon": "emoji_combo", "is_emoji": True}
            )
    if combo_terms:
        matched_terms.extend(combo_terms)

    if not matched_terms:
        # Emoji-only support: specific crime emojis + sale/CTA context are
        # actionable ("🍄 🍬 available dm for rates"); generic emojis and
        # emojis alone stay non-actionable.
        if has_intent_context and matched_emojis:
            matched_terms = _emoji_fallback_terms(store, matched_emojis, norm)
            if not matched_terms:
                return 0.0, [], [], "LOW"
        else:
            return 0.0, [], [], "LOW"

    anchor_terms: Set[str] = {
        item["term"]
        for item in matched_terms
        if item["term"] not in _AMBIGUOUS_TERMS
        and item["term"] not in _WEAK_OBJECT_TERMS
        and item["weight"] >= _ANCHOR_WEIGHT
    }

    # Weak objects need a real sale/rent/recruitment verb (not just "available"
    # or "delivery", which every legitimate ad uses) AND a contact identifier.
    strong_intent = bool(_STRONG_INTENT_RE.search(norm) or _BUYER_INTENT_RE.search(norm))
    matched_term_names = {item["term"] for item in matched_terms}
    contact_present = False
    if not anchor_terms and any(t in _WEAK_OBJECT_TERMS for t in matched_term_names):
        contact_present = bool(extract_identifiers(text))

    filtered: List[Dict] = []
    for item in matched_terms:
        term = item["term"]
        if term in _AMBIGUOUS_TERMS:
            if anchor_terms and has_intent_context:
                filtered.append(item)
        elif term in _WEAK_OBJECT_TERMS:
            if anchor_terms or (strong_intent and contact_present):
                filtered.append(item)
        else:
            filtered.append(item)

    if not filtered:
        # Every match was ambiguous/weak without corroboration, but specific
        # crime emojis + intent context can still carry the signal.
        if has_intent_context and matched_emojis:
            filtered = _emoji_fallback_terms(store, matched_emojis, norm)
        if not filtered:
            return 0.0, [], [], "LOW"

    score = 1.0
    for item in filtered:
        score *= 1.0 - item["weight"]
    score = min(1.0 - score, 1.0)

    if matched_emojis:
        score = min(1.0, score + 0.05)

    categories = sorted(list({item["category"] for item in filtered}))

    if any(c in CRITICAL_CATEGORIES for c in categories):
        severity = "CRITICAL"
    elif any(c in HIGH_CATEGORIES for c in categories):
        severity = "HIGH"
    elif any(c in PETTY_CATEGORIES for c in categories):
        severity = "PETTY"
    else:
        severity = "MEDIUM"

    return score, filtered, categories, severity


def ml_score(text: str) -> Optional[float]:
    if _ml_pipeline is None:
        return None
    try:
        prob = _ml_pipeline.predict_proba([text])[0]
        classes = list(_ml_pipeline.classes_)
        idx = classes.index(1) if 1 in classes else -1
        return float(prob[idx]) if idx >= 0 else None
    except Exception as exc:
        logger.debug("ML score failed: %s", exc)
        return None


def _risk_to_priority_tier(risk_level: str, threat_severity: str) -> str:
    if threat_severity == "CRITICAL":
        return "P1"
    rl = risk_level.lower()
    if rl == "high":
        return "P2"
    if rl == "medium":
        return "P3"
    return "P4"


class ClassificationResult:
    __slots__ = (
        "score",
        "risk_level",
        "severity_tier",
        "threat_severity",
        "is_serious",
        "categories",
        "matched_terms",
        "ml_score_val",
        "normalised_text",
        "category_confidence",
        "intent_confidence",
        "contact_signal",
        "negative_context_penalty",
        "scoring_version",
        "reason_codes",
        "evidence",
    )

    def __init__(
        self,
        score: float,
        risk_level: str,
        threat_severity: str,
        is_serious: bool,
        categories: List[str],
        matched_terms: List[Dict],
        ml_score_val: Optional[float],
        normalised_text: str = "",
        *,
        category_confidence: float = 0.0,
        intent_confidence: float = 0.0,
        contact_signal: float = 0.0,
        negative_context_penalty: float = 0.0,
        scoring_version: str = settings.SCORING_VERSION,
        reason_codes: Optional[List[str]] = None,
        ml_limitation: Optional[str] = None,
    ) -> None:
        self.score = score
        self.risk_level = risk_level
        self.threat_severity = threat_severity
        self.severity_tier = _risk_to_priority_tier(risk_level, threat_severity)
        self.is_serious = is_serious
        self.categories = categories
        self.matched_terms = matched_terms
        self.ml_score_val = ml_score_val
        self.normalised_text = normalised_text
        self.category_confidence = round(category_confidence, 4)
        self.intent_confidence = round(intent_confidence, 4)
        self.contact_signal = round(contact_signal, 4)
        self.negative_context_penalty = round(negative_context_penalty, 4)
        self.scoring_version = scoring_version
        self.reason_codes = reason_codes or []
        self.evidence = {
            "matched_terms": matched_terms,
            "severity_tier": self.severity_tier,
            "threat_severity": threat_severity,
            "is_serious": is_serious,
            "category_confidence": self.category_confidence,
            "intent_confidence": self.intent_confidence,
            "contact_signal": self.contact_signal,
            "negative_context_penalty": self.negative_context_penalty,
            "final_score": round(score, 4),
            "scoring_version": scoring_version,
            "reason_codes": self.reason_codes,
            "ml_score": ml_score_val,
            "ml_limitation": ml_limitation,
            "normalised_text": normalised_text,
        }

    @property
    def is_flagged(self) -> bool:
        return self.risk_level in ("HIGH", "MEDIUM")


def classify(text: str, *, profile: str = "illegal_trade") -> ClassificationResult:
    if not text or not text.strip():
        return ClassificationResult(0.0, "LOW", "LOW", False, [], [], None, normalised_text="")

    norm_text = normalise_text(text)
    store = get_lexicon_store()
    cat_conf, matched_terms, categories, severity = lexicon_score(text, store, profile=profile)

    if not matched_terms or cat_conf <= 0.0:
        return ClassificationResult(
            0.0, "LOW", "LOW", False, [], [], None,
            normalised_text=norm_text,
            reason_codes=["NO_CORE_CATEGORY_MATCH"],
        )

    intent_conf, contact_sig, neg_pen, reason_codes = _assess_intent_and_context(text, norm_text)
    if cat_conf >= _ANCHOR_WEIGHT:
        reason_codes.insert(0, "CATEGORY_ANCHOR")
    else:
        reason_codes.insert(0, "CATEGORY_KEYWORD")

    raw_score = (
        settings.SCORE_CATEGORY_WEIGHT * cat_conf
        + settings.SCORE_INTENT_WEIGHT * intent_conf
        + settings.SCORE_CONTACT_WEIGHT * contact_sig
        - neg_pen
    )
    raw_score = max(0.0, min(1.0, raw_score))

    ml_s: Optional[float] = None
    ml_limitation: Optional[str] = (
        "ML scoring disabled by default (unvalidated synthetic bootstrap model); using lexicon + intent + context."
    )
    if settings.USE_ML_SCORING:
        ml_s = ml_score(text)
        if ml_s is not None:
            # Symmetric weighted blend: ML can both raise AND lower raw_score
            final = max(0.0, min(1.0, settings.SCORE_LEXICON_WEIGHT * raw_score + settings.SCORE_ML_WEIGHT * ml_s))
            ml_limitation = None
        else:
            final = raw_score
    else:
        final = raw_score

    keyword_only = (intent_conf == 0.0 and contact_sig == 0.0)
    if keyword_only:
        final = min(final, settings.SCORE_KEYWORD_ONLY_CAP)
        reason_codes.append("KEYWORD_ONLY_CAPPED_BELOW_HIGH")

    if keyword_only:
        level = "MEDIUM" if final >= settings.MEDIUM_RISK_THRESHOLD else "LOW"
    elif severity == "CRITICAL" and final >= settings.MEDIUM_RISK_THRESHOLD and neg_pen == 0.0:
        level = "HIGH"
    elif final >= settings.HIGH_RISK_THRESHOLD:
        level = "HIGH"
    elif final >= settings.MEDIUM_RISK_THRESHOLD:
        level = "MEDIUM"
    else:
        level = "LOW"

    is_serious = severity in ("CRITICAL", "HIGH")
    return ClassificationResult(
        final,
        level,
        severity,
        is_serious,
        categories,
        matched_terms,
        ml_s,
        normalised_text=norm_text,
        category_confidence=cat_conf,
        intent_confidence=intent_conf,
        contact_signal=contact_sig,
        negative_context_penalty=neg_pen,
        scoring_version=settings.SCORING_VERSION,
        reason_codes=reason_codes,
        ml_limitation=ml_limitation,
    )
