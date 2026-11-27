"""
Default seed catalogue — populated into the DB on first startup.

Profile separation:
- Default "illegal_trade" profile covers ONLY the six core categories:
    drugs | arms | fake_documents | mule_accounts | cards | sim_cards
- Investment, colour-trading, crypto, betting, and generic scam seeds live in
  FINANCE_SCAM_SEED_CATALOGUE (profile="finance_scam" / "gambling_betting"),
  excluded from the default illegal-trade workflow unless explicitly selected.

Committed seeds contain generic, publicly known terms only.
Analyst-observed variants go in local Git-ignored data/local/seeds_overlay.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

CATALOGUE_VERSION = "2026.11.v1"

ILLEGAL_TRADE_CATEGORIES = (
    "drugs",
    "arms",
    "fake_documents",
    "mule_accounts",
    "cards",
    "sim_cards",
)

DEFAULT_LOCAL_SEEDS_OVERLAY = "../data/local/seeds_overlay.json"

DEFAULT_SEED_CATALOGUE: List[Dict[str, Any]] = [
    # ── 1. Drugs (12 seeds) ───────────────────────────────────────────────────
    {"seed_text": "ganja home delivery", "threat_category": "drugs", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Direct Hindi-English cannabis supply phrasing"},
    {"seed_text": "charas hashish sale", "threat_category": "drugs", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Cannabis resin sale indicator"},
    {"seed_text": "afeem opium available", "threat_category": "drugs", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Raw opium supply phrasing"},
    {"seed_text": "brown sugar smack sale", "threat_category": "drugs", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Street heroin supply indicator"},
    {"seed_text": "heroin chitta delivery", "threat_category": "drugs", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Regional heroin slang + delivery intent"},
    {"seed_text": "mdma molly ecstasy sale", "threat_category": "drugs", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Synthetic party drug sale"},
    {"seed_text": "crystal meth ice sale", "threat_category": "drugs", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Methamphetamine sale indicator"},
    {"seed_text": "cocaine coke supply", "threat_category": "drugs", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Cocaine supply phrasing"},
    {"seed_text": "lsd blotter acid sale", "threat_category": "drugs", "language_region": "en", "intent_type": "sale_or_supply", "priority": 2, "seed_role": "indicator", "status": "active", "rationale": "Psychedelic blotter sale"},
    {"seed_text": "stealth shipping narcotics", "threat_category": "drugs", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "discovery", "status": "active", "rationale": "Broad illicit narcotics shipping discovery"},
    {"seed_text": "गांजा चरस सप्लाई", "threat_category": "drugs", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari cannabis supply phrasing"},
    {"seed_text": "अफीम स्मैक उपलब्ध", "threat_category": "drugs", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari opioid/heroin availability"},

    # ── 2. Arms (10 seeds) ────────────────────────────────────────────────────
    {"seed_text": "desi katta pistol sale", "threat_category": "arms", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Country-made firearm sale"},
    {"seed_text": "tamancha 315 bore sale", "threat_category": "arms", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Regional illicit firearm calibre sale"},
    {"seed_text": "revolver 9mm bullets sale", "threat_category": "arms", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Handgun and ammunition sale"},
    {"seed_text": "illegal pistol ammunition", "threat_category": "arms", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Unlicensed firearm + ammo sale"},
    {"seed_text": "glock handgun delivery", "threat_category": "arms", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Imported pistol supply phrasing"},
    {"seed_text": "ak47 assault rifle sale", "threat_category": "arms", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Military-grade rifle trafficking"},
    {"seed_text": "live cartridges kartoos", "threat_category": "arms", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Live ammunition sale in Hinglish"},
    {"seed_text": "unlicensed firearm dealer", "threat_category": "arms", "language_region": "en", "intent_type": "sale_or_supply", "priority": 2, "seed_role": "discovery", "status": "active", "rationale": "Broad illicit arms dealer discovery"},
    {"seed_text": "देसी कट्टा पिस्तौल बिकाऊ", "threat_category": "arms", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari firearm for sale"},
    {"seed_text": "अवैध हथियार कारतूस", "threat_category": "arms", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari illegal weapons and cartridges"},

    # ── 3. Fake Documents (10 seeds) ──────────────────────────────────────────
    {"seed_text": "fake aadhaar card maker", "threat_category": "fake_documents", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Forged national ID card creation"},
    {"seed_text": "fake pan card sale", "threat_category": "fake_documents", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Forged tax ID card sale"},
    {"seed_text": "forged passport driving licence", "threat_category": "fake_documents", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Counterfeit travel/driver documents"},
    {"seed_text": "fake degree certificate sale", "threat_category": "fake_documents", "language_region": "en", "intent_type": "sale_or_supply", "priority": 2, "seed_role": "indicator", "status": "active", "rationale": "Counterfeit academic credentials"},
    {"seed_text": "kyc document edit psd", "threat_category": "fake_documents", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Editable ID templates for KYC bypass"},
    {"seed_text": "nakli aadhar pan card", "threat_category": "fake_documents", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Hinglish forged ID document phrasing"},
    {"seed_text": "farzi marksheet certificate", "threat_category": "fake_documents", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 2, "seed_role": "indicator", "status": "active", "rationale": "Hinglish counterfeit academic certificate"},
    {"seed_text": "fake voter id birth certificate", "threat_category": "fake_documents", "language_region": "en", "intent_type": "sale_or_supply", "priority": 2, "seed_role": "indicator", "status": "active", "rationale": "Forged civil identity documents"},
    {"seed_text": "नकली आधार पैन कार्ड", "threat_category": "fake_documents", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari forged ID documents"},
    {"seed_text": "फर्जी दस्तावेज पासपोर्ट", "threat_category": "fake_documents", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari forged passport/documents"},

    # ── 4. Mule Accounts (10 seeds) ───────────────────────────────────────────
    {"seed_text": "mule bank account wanted", "threat_category": "mule_accounts", "language_region": "en", "intent_type": "rental_or_recruitment", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Explicit mule account recruitment"},
    {"seed_text": "bank account on rent", "threat_category": "mule_accounts", "language_region": "en", "intent_type": "rental_or_recruitment", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Bank account rental for laundering"},
    {"seed_text": "corporate current account sale", "threat_category": "mule_accounts", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Corporate mule account kit sale"},
    {"seed_text": "kyc verified bank kit", "threat_category": "mule_accounts", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Full KYC bank kit sale"},
    {"seed_text": "saving account chahiye commission", "threat_category": "mule_accounts", "language_region": "hinglish", "intent_type": "rental_or_recruitment", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Hinglish mule account commission offer"},
    {"seed_text": "khata kiraye par chahiye", "threat_category": "mule_accounts", "language_region": "hinglish", "intent_type": "rental_or_recruitment", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Hinglish bank account rental demand"},
    {"seed_text": "netbanking passbook cheque kit", "threat_category": "mule_accounts", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Complete mule banking instrument kit"},
    {"seed_text": "merchant upi account rent", "threat_category": "mule_accounts", "language_region": "en", "intent_type": "rental_or_recruitment", "priority": 1, "seed_role": "discovery", "status": "active", "rationale": "Merchant payment mule recruitment"},
    {"seed_text": "बैंक खाता किराए पर", "threat_category": "mule_accounts", "language_region": "hi", "intent_type": "rental_or_recruitment", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari bank account rental"},
    {"seed_text": "म्यूल अकाउंट कमीशन", "threat_category": "mule_accounts", "language_region": "hi", "intent_type": "rental_or_recruitment", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari mule account recruitment"},

    # ── 5. Cards (10 seeds) ───────────────────────────────────────────────────
    {"seed_text": "atm debit card sale", "threat_category": "cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Physical ATM/debit card sale"},
    {"seed_text": "cloned credit card cvv", "threat_category": "cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Cloned card and CVV trafficking"},
    {"seed_text": "cc dump track2 fullz", "threat_category": "cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Carding dumps and fullz sale"},
    {"seed_text": "fresh non vbv bins", "threat_category": "cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Non-3DS carding BINs sale"},
    {"seed_text": "skimmed atm card pin", "threat_category": "cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Skimmed ATM card + PIN sale"},
    {"seed_text": "rupay visa debit kit", "threat_category": "cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 2, "seed_role": "indicator", "status": "active", "rationale": "Domestic/international debit card kit"},
    {"seed_text": "atm card rent commission", "threat_category": "cards", "language_region": "hinglish", "intent_type": "rental_or_recruitment", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "ATM card rental for cashout"},
    {"seed_text": "debit card pin available", "threat_category": "cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 2, "seed_role": "discovery", "status": "active", "rationale": "Broad debit card + PIN discovery"},
    {"seed_text": "एटीएम डेबिट कार्ड बिकाऊ", "threat_category": "cards", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari ATM/debit card for sale"},
    {"seed_text": "क्रेडिट कार्ड सीवीवी डेटा", "threat_category": "cards", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari stolen card CVV data"},

    # ── 6. SIM Cards (10 seeds) ───────────────────────────────────────────────
    {"seed_text": "pre activated sim card sale", "threat_category": "sim_cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Pre-activated KYC-bypassed SIM sale"},
    {"seed_text": "registered sim card bulk", "threat_category": "sim_cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Bulk KYC-registered SIM supply"},
    {"seed_text": "fake kyc sim card", "threat_category": "sim_cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "SIM issued on forged KYC"},
    {"seed_text": "sim swap otp bypass", "threat_category": "sim_cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Illicit SIM swap / OTP interception"},
    {"seed_text": "esim without kyc sale", "threat_category": "sim_cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Anonymous eSIM sale"},
    {"seed_text": "bina document sim card", "threat_category": "sim_cards", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Hinglish no-KYC SIM sale"},
    {"seed_text": "chalu sim card chahiye", "threat_category": "sim_cards", "language_region": "hinglish", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Hinglish pre-activated SIM demand"},
    {"seed_text": "international burner sim sale", "threat_category": "sim_cards", "language_region": "en", "intent_type": "sale_or_supply", "priority": 2, "seed_role": "discovery", "status": "active", "rationale": "Burner SIM discovery"},
    {"seed_text": "बिना केवाईसी सिम कार्ड", "threat_category": "sim_cards", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari no-KYC SIM card"},
    {"seed_text": "चालू सिम कार्ड बिकाऊ", "threat_category": "sim_cards", "language_region": "hi", "intent_type": "sale_or_supply", "priority": 1, "seed_role": "indicator", "status": "active", "rationale": "Devanagari active SIM card for sale"},
]

# Separated non-default profiles (never active in default illegal-trade workflow)
FINANCE_SCAM_SEED_CATALOGUE: List[Dict[str, Any]] = [
    {"seed_text": "colour prediction group", "threat_category": "colour_trading_scam", "profile": "finance_scam", "language_region": "en", "intent_type": "rental_or_recruitment", "priority": 4, "seed_role": "discovery", "status": "paused", "rationale": "Separated colour-trading profile"},
    {"seed_text": "guaranteed return investment", "threat_category": "investment_fraud", "profile": "finance_scam", "language_region": "en", "intent_type": "rental_or_recruitment", "priority": 4, "seed_role": "discovery", "status": "paused", "rationale": "Separated investment-fraud profile"},
    {"seed_text": "crypto doubler group", "threat_category": "investment_fraud", "profile": "finance_scam", "language_region": "en", "intent_type": "rental_or_recruitment", "priority": 4, "seed_role": "discovery", "status": "paused", "rationale": "Separated crypto-scam profile"},
    {"seed_text": "ipl satta matka betting", "threat_category": "gambling_scam", "profile": "gambling_betting", "language_region": "hinglish", "intent_type": "rental_or_recruitment", "priority": 4, "seed_role": "discovery", "status": "paused", "rationale": "Separated gambling/betting profile"},
]


def load_local_seeds_overlay(overlay_path: str = DEFAULT_LOCAL_SEEDS_OVERLAY) -> List[Dict[str, Any]]:
    """Load analyst-observed seeds from local Git-ignored overlay file if present."""
    p = Path(overlay_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict) and item.get("seed_text")]
    except Exception:
        return []
    return []
