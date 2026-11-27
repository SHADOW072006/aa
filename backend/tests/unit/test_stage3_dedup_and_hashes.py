"""
Stage 3 unit tests:
- One EvidenceObservation per collection event (no duplicate writes on flagged messages)
- Hash propagation to Message, EvidenceMessage, and EvidenceObservation
- Historical provenance backfill (dry run, retained text, missing content, unavailable media, idempotency)
- Unavailable/purged media reported as 'not_currently_verifiable'
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.classifiers.lexicon_loader import init_lexicons
from app.collectors import telegram_collector
from app.core.config import settings
from app.db.models import Base, Channel, EvidenceMessage, EvidenceObservation, Message
from app.services.evidence_hashing import backfill_provenance_hashes, verify_record_hashes


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


@pytest.mark.asyncio
async def test_single_observation_per_flagged_collection_event(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def _test_session():
        async with Session() as s:
            yield s
            await s.commit()

    monkeypatch.setattr(telegram_collector, "get_session", _test_session)

    async with Session() as s:
        ch = Channel(username="placeholder_obs_ch", is_active=True, poll_tier="LOW")
        s.add(ch)
        await s.commit()

    collector = object.__new__(telegram_collector.TelegramCollector)
    tg_msg = SimpleNamespace(
        id=7001,
        message="heroin available for sale dm me @placeholder_dealer",
        media=None,
        sender_id=12345,
        sender=SimpleNamespace(username="placeholder_sender"),
        date=datetime(2025, 3, 1, 12, 0, 0),
    )

    await collector._process_message(tg_msg, ch)

    async with Session() as s:
        msg = (await s.execute(select(Message))).scalar_one()
        em = (await s.execute(select(EvidenceMessage))).scalar_one()
        obs_count = (await s.execute(select(func.count(EvidenceObservation.id)))).scalar_one()
        obs = (await s.execute(select(EvidenceObservation))).scalar_one()

        assert obs_count == 1  # exactly ONE observation, not 2
        assert msg.original_text_hash is not None
        assert msg.evidence_hash is not None
        assert msg.provenance_status == "verified_hashes"
        assert em.original_text_hash == msg.original_text_hash
        assert em.evidence_hash == msg.evidence_hash
        assert obs.observation_hash is not None

    await engine.dispose()


def test_unavailable_media_reported_not_currently_verifiable():
    res = verify_record_hashes(
        raw_text="[placeholder text]",
        stored_original_text_hash=None,
        media_path="/nonexistent/purged_media.jpg",
        stored_media_hash="a" * 64,
        source_platform="telegram",
        channel_identifier="placeholder_ch",
        source_message_id=10,
        post_timestamp=datetime(2025, 3, 1, 12, 0, 0),
        stored_evidence_hash="b" * 64,
        has_media=True,
    )
    assert res["verification_status"] == "unavailable"
    assert res["overall_match"] is False


@pytest.mark.asyncio
async def test_backfill_dry_run_missing_content_unverifiable_and_idempotent():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as s:
        ch = Channel(username="placeholder_bf_ch", is_active=True)
        s.add(ch)
        await s.flush()

        m_text = Message(
            channel_id=ch.id, telegram_msg_id=1, text="[placeholder retained]",
            has_media=False, created_at=datetime(2025, 1, 1, 10, 0, 0), source="telegram",
        )
        m_missing = Message(
            channel_id=ch.id, telegram_msg_id=2, text=None,
            has_media=False, created_at=datetime(2025, 1, 1, 10, 5, 0), source="telegram",
        )
        m_media = Message(
            channel_id=ch.id, telegram_msg_id=3, text="[placeholder caption]",
            has_media=True, media_path="/missing/file.jpg",
            created_at=datetime(2025, 1, 1, 10, 10, 0), source="telegram",
        )
        s.add_all([m_text, m_missing, m_media])
        await s.flush()

        dry = await backfill_provenance_hashes(s, actor="test", dry_run=True)
        assert dry["backfilled"] == 1
        assert dry["missing_content"] == 1
        assert dry["unverifiable_media"] == 1
        assert m_text.evidence_hash is None  # untouched on dry run

        live = await backfill_provenance_hashes(s, actor="test", dry_run=False)
        assert live["backfilled"] == 1
        assert live["missing_content"] == 1
        assert live["unverifiable_media"] == 1
        assert m_text.evidence_hash is not None
        assert m_text.provenance_status == "hash_backfilled"
        assert m_missing.evidence_hash is None
        assert m_missing.provenance_status == "missing_content"
        assert m_media.evidence_hash is None
        assert m_media.provenance_status == "unverifiable_media"

        # Idempotent re-run
        again = await backfill_provenance_hashes(s, actor="test", dry_run=False)
        assert again["backfilled"] == 0
        assert again["missing_content"] == 0
        assert again["unverifiable_media"] == 0

    await engine.dispose()

