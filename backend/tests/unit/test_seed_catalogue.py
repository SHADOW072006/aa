"""
Stage 2 unit tests: seed catalogue, profile separation, lifecycle,
local overlay merge, and Devanagari matching.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.classifiers.classifier import lexicon_score
from app.classifiers.lexicon_loader import LexiconStore
from app.db.models import AuditLog, Base
from app.extractors.normaliser import normalise
from app.services.seed_defaults import (
    DEFAULT_SEED_CATALOGUE,
    FINANCE_SCAM_SEED_CATALOGUE,
    ILLEGAL_TRADE_CATEGORIES,
    load_local_seeds_overlay,
)
from app.services.seed_service import (
    create_seed,
    generate_variants,
    get_active_variants,
    get_seed_summary,
    transition_seed_status,
)


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


def test_default_catalogue_required_fields_and_unique_normalised():
    assert len(DEFAULT_SEED_CATALOGUE) >= 60
    seen = set()
    for entry in DEFAULT_SEED_CATALOGUE:
        for field in ("seed_text", "threat_category", "language_region", "intent_type", "priority", "status", "rationale"):
            assert entry.get(field) not in (None, ""), f"Missing {field} in {entry}"
        assert entry["language_region"] in ("en", "hi", "hinglish")
        norm = normalise(entry["seed_text"])
        assert norm not in seen, f"Duplicate normalised seed: {norm}"
        seen.add(norm)


def test_default_catalogue_covers_six_categories_and_excludes_finance():
    cats = {e["threat_category"] for e in DEFAULT_SEED_CATALOGUE}
    assert cats == set(ILLEGAL_TRADE_CATEGORIES)
    assert len(FINANCE_SCAM_SEED_CATALOGUE) >= 1
    for entry in FINANCE_SCAM_SEED_CATALOGUE:
        assert entry.get("profile") != "illegal_trade"


def test_devanagari_normalisation_and_lexicon_matching(tmp_path):
    phrase = "गांजा उपलब्ध है"
    assert normalise(phrase) == phrase

    overlay = tmp_path / "lexicon_overlay.json"
    overlay.write_text(
        json.dumps({"terms": {"गांजा": {"category": "cannabis", "weight": 0.85}}, "emojis": {}}),
        encoding="utf-8",
    )
    store = LexiconStore()
    store.load(overlay, "local_overlay")
    score, matched, cats, _ = lexicon_score("गांजा उपलब्ध है", store)
    assert score >= 0.85
    assert "cannabis" in cats
    assert any(m["term"] == "गांजा" for m in matched)


def test_local_seeds_overlay_merge(tmp_path):
    overlay = tmp_path / "seeds_overlay.json"
    overlay.write_text(
        json.dumps([{"seed_text": "placeholder local seed", "threat_category": "drugs", "intent_type": "sale_or_supply"}]),
        encoding="utf-8",
    )
    loaded = load_local_seeds_overlay(str(overlay))
    assert len(loaded) == 1
    assert loaded[0]["seed_text"] == "placeholder local seed"


def test_variant_generation_hinglish_and_hi():
    v_hi = generate_variants("गांजा चरस", "hi")
    assert len(v_hi) >= 3
    v_hing = generate_variants("desi katta", "hinglish")
    assert len(v_hing) >= 3


@pytest.mark.asyncio
async def test_seed_lifecycle_approval_and_profile_filtering(db):
    # Broad discovery seed starts as 'proposed' unless approved_by is passed
    s_disc = await create_seed(
        db,
        seed_text="broad placeholder discovery",
        threat_category="drugs",
        language_region="en",
        intent_type="sale_or_supply",
        priority=2,
        created_source="manual",
        profile="illegal_trade",
        seed_role="discovery",
        rationale="Needs analyst approval",
    )
    assert s_disc.status == "proposed"
    assert s_disc.is_active is False

    # Finance seed excluded from default illegal_trade active variants
    s_fin = await create_seed(
        db,
        seed_text="placeholder investment group",
        threat_category="investment_fraud",
        language_region="en",
        intent_type="rental_or_recruitment",
        priority=4,
        created_source="manual",
        profile="finance_scam",
        seed_role="discovery",
        approved_by="analyst_a",
    )
    assert s_fin.status == "active"
    active_default = await get_active_variants(db, profile="illegal_trade")
    assert all(sp.profile == "illegal_trade" for _, sp in active_default)

    # Activate proposed discovery seed with analyst approval -> audit logged
    s_act = await transition_seed_status(db, s_disc.id, "active", actor="analyst_a", rationale="Approved")
    assert s_act.status == "active"
    assert s_act.is_active is True

    # Pause -> Retire
    s_paused = await transition_seed_status(db, s_disc.id, "paused", actor="analyst_a")
    assert s_paused.status == "paused"
    s_ret = await transition_seed_status(db, s_disc.id, "retired", actor="analyst_a")
    assert s_ret.status == "retired"
    assert s_ret.is_active is False

    logs = (await db.execute(select(AuditLog).where(AuditLog.action == "seed_status_change"))).scalars().all()
    assert len(logs) >= 4

    summary = await get_seed_summary(db)
    assert summary["total"] == 2


@pytest.mark.asyncio
async def test_idempotent_sync_and_stale_catalogue_upgrade(db):
    from app.db.crud import create_seed_profile, list_seed_profiles
    from app.services.seed_service import sync_seed_catalogue

    # Simulate stale DB: 1 scam, 1 gambling, 1 cybercrime, 1 matching core seed
    await create_seed_profile(
        db, seed_text="colour prediction group", threat_category="scam",
        language_region="en", intent_type="recruitment", priority=2, created_source="default",
    )
    await create_seed_profile(
        db, seed_text="ipl satta matka betting", threat_category="gambling",
        language_region="en", intent_type="recruitment", priority=3, created_source="default",
    )
    await create_seed_profile(
        db, seed_text="aadhaar database dump", threat_category="cybercrime",
        language_region="en", intent_type="data_breach", priority=1, created_source="default",
    )
    await create_seed_profile(
        db, seed_text="desi katta pistol sale", threat_category="arms",
        language_region="en", intent_type="arms_sale", priority=1, created_source="default",
    )

    res1 = await sync_seed_catalogue(db)
    assert res1["active_illegal_trade_count"] == len(DEFAULT_SEED_CATALOGUE)
    assert res1["moved_non_core"] >= 1

    # Re-running sync must be idempotent (0 created, 0 updated)
    res2 = await sync_seed_catalogue(db)
    assert res2["created"] == 0
    assert res2["updated"] == 0
    assert res2["active_illegal_trade_count"] == len(DEFAULT_SEED_CATALOGUE)

    # Default illegal_trade active seeds contain ONLY the 6 allowed categories
    active_core = await list_seed_profiles(db, is_active=True, profile="illegal_trade", status="active", limit=500)
    assert len(active_core) == len(DEFAULT_SEED_CATALOGUE)
    assert {s.threat_category for s in active_core} == set(ILLEGAL_TRADE_CATEGORIES)

    # Stale non-core seeds were moved & paused, NOT deleted
    all_rows = await list_seed_profiles(db, limit=500)
    by_norm = {s.seed_text_normalised: s for s in all_rows}
    assert by_norm["aadhaar database dump"].profile == "extended_legacy"
    assert by_norm["aadhaar database dump"].status == "paused"
    assert by_norm["aadhaar database dump"].is_active is False


@pytest.mark.asyncio
async def test_custom_scan_seed_isolation(db, monkeypatch):
    from contextlib import asynccontextmanager
    from app.collectors import scanner

    # Seed DB with an active illegal_trade seed
    await create_seed(
        db, seed_text="placeholder db seed", threat_category="drugs",
        language_region="en", intent_type="sale_or_supply", priority=1, created_source="manual",
    )

    searched_queries = []

    class _FakeClient:
        def is_connected(self):
            return True

        async def is_user_authorized(self):
            return True

    class _FakeCollector:
        client = _FakeClient()

    async def _fake_search(_client, q):
        searched_queries.append(q)
        return []

    @asynccontextmanager
    async def _test_session():
        yield db
        await db.flush()

    monkeypatch.setattr(scanner, "get_session", _test_session)
    monkeypatch.setattr("app.collectors.telegram_collector.get_collector", lambda: _FakeCollector())
    monkeypatch.setattr(scanner, "_search_channels", _fake_search)

    from app.db.models import ScanJob
    job = ScanJob(seed_terms='["only custom query"]', status="pending")
    db.add(job)
    await db.flush()

    await scanner._run_scan_job(job.id, ["only custom query"], mode="review", profile="illegal_trade", is_custom=True)
    assert searched_queries == ["only custom query"]
    assert "placeholder db seed" not in searched_queries


