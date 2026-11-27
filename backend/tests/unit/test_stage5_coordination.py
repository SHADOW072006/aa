"""
Stage 5 (P1) unit tests: MinHash/LSH near-duplicate detection,
DB rebuild at startup, channel coordination graph edges, and
optional image_path OCR + media_hash in CSV/JSON import.
Uses minimal neutral placeholder strings and generated blank PNG bytes only.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.classifiers.lexicon_loader import init_lexicons
from app.collectors import import_handler
from app.core.config import settings
from app.db.models import Base, Channel, Identifier, Message
from app.graph.entity_graph import build_graph, get_graph_json
from app.services.minhash_service import (
    NearDuplicateIndex,
    compute_minhash,
    get_minhash_index,
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


def test_minhash_skips_short_posts():
    assert compute_minhash("one two three four") is None
    assert compute_minhash("one two three four five six") is not None


@pytest.mark.asyncio
async def test_minhash_near_duplicate_cross_channel_and_graph_edges(db):
    idx = get_minhash_index()
    idx.reset()

    ch1 = Channel(username="placeholder_alpha", is_active=True)
    ch2 = Channel(username="placeholder_beta", is_active=True)
    db.add_all([ch1, ch2])
    await db.flush()

    text1 = "placeholder item available for fast local delivery contact handle today"
    text2 = "placeholder item available for fast local delivery contact handle now"

    m1 = Message(channel_id=ch1.id, telegram_msg_id=1, text=text1, created_at=datetime.utcnow(), source="telegram")
    m2 = Message(channel_id=ch2.id, telegram_msg_id=2, text=text2, created_at=datetime.utcnow(), source="telegram")
    db.add_all([m1, m2])
    await db.flush()

    sig1, hits1 = idx.add_message(m1.id, ch1.id, text1)
    m1.minhash_sig = sig1
    assert hits1 == []

    sig2, hits2 = idx.add_message(m2.id, ch2.id, text2)
    m2.minhash_sig = sig2
    assert ch1.id in hits2

    # Rebuild from DB and verify index still finds the cross-channel link
    rebuilt = NearDuplicateIndex()
    loaded = await rebuilt.rebuild_from_db(db)
    assert loaded == 2
    assert ch1.id in rebuilt.query_similar_channels(m2.minhash_sig, ch2.id)

    # Shared identifier across channels
    id1 = Identifier(message_id=m1.id, type="handle", value="@placeholder_h", normalised="placeholder_h")
    id2 = Identifier(message_id=m2.id, type="handle", value="@placeholder_h", normalised="placeholder_h")
    db.add_all([id1, id2])
    await db.flush()

    G = await build_graph(db)
    g_json = get_graph_json(G)
    reasons = set()
    for el in g_json["elements"]:
        r = el["data"].get("reason")
        if r:
            reasons.update(r.split(","))
    assert "near_duplicate_text" in reasons
    assert "shared_identifier" in reasons


@pytest.mark.asyncio
async def test_import_optional_image_path_ocr_and_media_hash(monkeypatch, tmp_path):
    init_lexicons(
        drug_path=settings.DRUG_LEXICON_PATH,
        financial_path=settings.FINANCIAL_LEXICON_PATH,
        arms_path=settings.ARMS_LEXICON_PATH,
        scam_path=settings.SCAM_LEXICON_PATH,
        extended_path=settings.EXTENDED_LEXICON_PATH,
        overlay_path="",
    )

    # Generate a minimal blank 1x1 PNG file (no real content) inside IMPORT_MEDIA_ROOT
    monkeypatch.setattr(settings, "IMPORT_MEDIA_ROOT", str(tmp_path))
    img_path = tmp_path / "blank.png"
    img_path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
        b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    async def _fake_ocr(_path: str):
        return "[placeholder ocr extracted string]"

    monkeypatch.setattr(import_handler, "extract_text_from_image", _fake_ocr)
    monkeypatch.setattr(import_handler, "_ocr_cache", {})

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

    res = await import_handler.process_rows(
        [{"channel": "placeholder_img_ch", "text": "[placeholder caption]", "image_attachment": "blank.png"}],
        default_source="json_import",
        filename="img_batch.json",
    )
    assert res["imported"] == 1
    assert res["errors"] == 0

    async with Session() as s:
        from sqlalchemy import select
        msg = (await s.execute(select(Message))).scalar_one()
        assert msg.ocr_text == "[placeholder ocr extracted string]"
        assert msg.media_hash is not None and len(msg.media_hash) == 64
        assert msg.evidence_hash is not None and len(msg.evidence_hash) == 64

    await engine.dispose()
