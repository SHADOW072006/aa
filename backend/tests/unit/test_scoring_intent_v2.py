"""
Stage 3 unit tests: intent-aware, explainable scoring (intent_v2).
Uses minimal neutral placeholder strings only.
"""
from __future__ import annotations

import pytest

from app.classifiers import classifier as clf_mod
from app.classifiers.lexicon_loader import init_lexicons
from app.core.config import settings


@pytest.fixture(autouse=True, scope="module")
def _init_lex():
    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
        overlay_path="",
    )


def test_emoji_only_non_actionable():
    res = clf_mod.classify("✅ 🏆 💰 💊")
    assert res.score == 0.0
    assert res.risk_level == "LOW"
    assert res.categories == []


def test_keyword_alone_cannot_produce_high():
    # Single category keyword with NO sale/rent/CTA intent and NO contact identifier
    res = clf_mod.classify("placeholder text mentioning heroin")
    assert res.risk_level != "HIGH"
    assert res.score <= settings.SCORE_KEYWORD_ONLY_CAP
    assert "KEYWORD_ONLY_CAPPED_BELOW_HIGH" in res.reason_codes


def test_sale_intent_and_contact_produce_explainable_high():
    res = clf_mod.classify("heroin available for sale, dm me @placeholder_handle_x")
    assert res.risk_level == "HIGH"
    assert res.category_confidence > 0.0
    assert res.intent_confidence > 0.0
    assert res.contact_signal > 0.0
    assert res.scoring_version == settings.SCORING_VERSION
    assert "SALE_OR_RENT_INTENT" in res.reason_codes
    assert "CONTACT_IDENTIFIER_PRESENT" in res.reason_codes
    assert res.evidence["scoring_version"] == settings.SCORING_VERSION


def test_investment_and_colour_trading_excluded_from_default_profile():
    res1 = clf_mod.classify("colour prediction group guaranteed return investment daily income")
    assert res1.risk_level == "LOW"
    assert res1.categories == []
    assert "NO_CORE_CATEGORY_MATCH" in res1.reason_codes


def test_negative_context_penalises_news_and_awareness():
    res = clf_mod.classify("Breaking news: police arrested suspect and seized heroin in awareness report")
    assert res.negative_context_penalty > 0.0
    assert "NEGATIVE_CONTEXT_PENALTY" in res.reason_codes
    assert res.risk_level != "HIGH"


def test_ambiguous_term_needs_anchor_and_intent():
    # Ambiguous term alone ("ice") without anchor + intent
    res_plain = clf_mod.classify("ice price is high today")
    assert res_plain.score == 0.0
    assert res_plain.risk_level == "LOW"


def test_ml_symmetric_blend_can_lower_score(monkeypatch):
    monkeypatch.setattr(settings, "USE_ML_SCORING", True)
    monkeypatch.setattr(clf_mod, "ml_score", lambda _t: 0.0)
    res_with_ml = clf_mod.classify("heroin available for sale, dm me @placeholder_handle_x")

    monkeypatch.setattr(settings, "USE_ML_SCORING", False)
    res_no_ml = clf_mod.classify("heroin available for sale, dm me @placeholder_handle_x")

    assert res_with_ml.score < res_no_ml.score

