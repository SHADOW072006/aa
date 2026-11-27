"""
Stage 4 unit tests: evidence hashing, chain-of-custody verification,
identifier fixes & masking, import dedup (no ID collision), retention purge,
graph edge metadata, and API token protection.
Uses minimal neutral placeholder strings only.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import AuditLog, Base, Channel, Identifier, Message
from app.extractors.identifier_extractor import extract, mask_identifier
from app.services.evidence_hashing import (
    compute_evidence_hash,
    compute_media_hash,
    compute_observation_hash,
    compute_original_text_hash,
    verify_record_hashes,
)
from app.services.retention_service import require_api_token, run_retention_purge


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


def test_evidence_hashing_and_verification(tmp_path):
    raw_text = "[placeholder neutral ad text]"
    ts = datetime(2025, 3, 1, 10, 0, 0)
    media_file = tmp_path / "sample.bin"
    media_file.write_bytes(b"placeholder-bytes-123")

    t_hash = compute_original_text_hash(raw_text)
    m_hash = compute_media_hash(media_file)
    ev_hash = compute_evidence_hash(
        source_platform="telegram",
        channel_identifier="placeholder_ch",
        source_message_id=101,
        post_timestamp=ts,
        original_text_hash=t_hash,
        media_hashes=[m_hash],
    )
    obs_hash = compute_observation_hash(
        evidence_hash=ev_hash,
        collected_at=ts,
        collector_or_batch_id="telegram_collector",
    )
    assert len(t_hash) == 64
    assert len(m_hash) == 64
    assert len(ev_hash) == 64
    assert len(obs_hash) == 64
    assert compute_original_text_hash("") is None

    res_ok = verify_record_hashes(
        raw_text=raw_text,
        stored_original_text_hash=t_hash,
        media_path=str(media_file),
        stored_media_hash=m_hash,
        source_platform="telegram",
        channel_identifier="placeholder_ch",
        source_message_id=101,
        post_timestamp=ts,
        stored_evidence_hash=ev_hash,
    )
    assert res_ok["overall_match"] is True

    res_tampered = verify_record_hashes(
        raw_text="tampered text",
        stored_original_text_hash=t_hash,
        media_path=str(media_file),
        stored_media_hash=m_hash,
        source_platform="telegram",
        channel_identifier="placeholder_ch",
        source_message_id=101,
        post_timestamp=ts,
        stored_evidence_hash=ev_hash,
    )
    assert res_tampered["overall_match"] is False


def test_identifier_fixes_and_masking():
    # 1. Email must not produce UPI or handle
    idents_email = extract("reach out at placeholder@example.com")
    types_email = {i.type for i in idents_email}
    assert "email" in types_email
    assert "upi" not in types_email
    assert "handle" not in types_email

    # 2. UPI must not produce handle
    idents_upi = extract("pay via placeholder@oksbi")
    types_upi = {i.type for i in idents_upi}
    assert "upi" in types_upi
    assert "handle" not in types_upi

    # 3. Spaced & emoji digits in phone numbers
    idents_phone = extract("call 9️⃣8️⃣7️⃣6️⃣5️⃣ 4️⃣3️⃣2️⃣1️⃣0️⃣ or +91 98765-43211")
    phones = {i.normalised for i in idents_phone if i.type == "phone"}
    assert "+919876543210" in phones
    assert "+919876543211" in phones

    # 4. Masking
    assert mask_identifier("phone", "9876543210") == "98xxxxxx10"
    assert mask_identifier("upi", "alice@oksbi") == "al***@oksbi"
    assert mask_identifier("handle", "@dealername") == "@de***"


@pytest.mark.asyncio
async def test_retention_purge_preserves_hashes_and_logs(db, tmp_path):
    old_ts = datetime.utcnow() - timedelta(days=120)
    ch = Channel(username="placeholder_ret_ch", is_active=True)
    db.add(ch)
    await db.flush()

    media_file = tmp_path / "old_media.bin"
    media_file.write_bytes(b"old-bytes")
    m_hash = compute_media_hash(media_file)
    t_hash = compute_original_text_hash("[placeholder old text]")

    msg = Message(
        channel_id=ch.id,
        telegram_msg_id=5001,
        text="[placeholder old text]",
        ocr_text="[placeholder old ocr]",
        original_text_hash=t_hash,
        media_hash=m_hash,
        evidence_hash="e" * 64,
        has_media=True,
        media_path=str(media_file),
        created_at=old_ts,
        collected_at=old_ts,
        source="telegram",
    )
    db.add(msg)
    await db.flush()

    stats = await run_retention_purge(db, actor="test_scheduler", exports_dir=str(tmp_path))
    assert stats["purged_raw_text"] == 1
    assert stats["purged_ocr_text"] == 1
    assert stats["purged_media"] == 1
    assert msg.text is None
    assert msg.ocr_text is None
    assert msg.media_path is None
    # Hashes preserved!
    assert msg.original_text_hash == t_hash
    assert msg.media_hash == m_hash
    assert msg.evidence_hash == "e" * 64

    logs = (await db.execute(select(AuditLog))).scalars().all()
    assert len(logs) == 3


@pytest.mark.asyncio
async def test_api_token_protection(monkeypatch):
    class _Client:
        host = "127.0.0.1"

    class _Req:
        client = _Client()

    monkeypatch.setattr(settings, "API_ACCESS_TOKEN", "secret-token-123")
    with pytest.raises(HTTPException) as exc:
        await require_api_token(_Req(), authorization=None, x_api_key=None)
    assert exc.value.status_code == 401

    actor = await require_api_token(_Req(), authorization="Bearer secret-token-123", x_api_key=None)
    assert actor == "token_authenticated"


@pytest.mark.asyncio
async def test_import_dedup_no_id_collision(monkeypatch):
    from contextlib import asynccontextmanager
    from app.collectors import import_handler
    from app.classifiers.lexicon_loader import init_lexicons

    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
        overlay_path="",
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def _test_session():
        async with Session() as s:
            yield s
            await s.commit()

    monkeypatch.setattr(import_handler, "get_session", _test_session)

    rows = [
        {"channel": "placeholder_import_ch", "text": "[placeholder neutral post 1]", "created_at": "2025-03-01 10:00:00"},
        {"channel": "placeholder_import_ch", "text": "[placeholder neutral post 2]", "created_at": "2025-03-01 10:05:00"},
    ]
    res1 = await import_handler.process_rows(rows, default_source="csv_import", filename="b1.csv")
    assert res1["imported"] == 2
    assert res1["duplicates"] == 0
    assert res1["errors"] == 0

    # Re-importing the exact same rows must NOT collide on negative IDs; must record duplicates
    res2 = await import_handler.process_rows(rows, default_source="csv_import", filename="b2.csv")
    assert res2["imported"] == 0
    assert res2["duplicates"] == 2
    assert res2["errors"] == 0

    await engine.dispose()

