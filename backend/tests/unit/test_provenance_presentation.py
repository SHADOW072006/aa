"""
Stage C unit tests: provenance-state presentation, hash verification statuses,
raw-content protection, and PDF provenance notices.
Uses neutral placeholder records only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import Alert, Channel, EvidenceMessage, Message
from app.main import app
from app.reports.pdf_generator import generate_channel_dossier_pdf
from app.services.evidence_hashing import (
    UNVERIFIABLE_MEDIA_NOTE,
    compute_evidence_hash,
    compute_media_hash,
    compute_original_text_hash,
    verify_record_hashes,
)


def test_verify_record_hashes_all_statuses(tmp_path: Path):
    now = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
    text = "neutral public sample message 1001"
    text_hash = compute_original_text_hash(text)

    media_file = tmp_path / "sample_media.bin"
    media_file.write_bytes(b"neutral-media-bytes-001")
    media_hash = compute_media_hash(media_file)
    assert media_hash is not None

    ev_hash_with_media = compute_evidence_hash(
        source_platform="telegram",
        channel_identifier="neutral_channel_c",
        source_message_id=1001,
        post_timestamp=now,
        original_text_hash=text_hash,
        media_hashes=[media_hash],
    )

    # 1. Retained evidence -> verified
    verified = verify_record_hashes(
        raw_text=text,
        stored_original_text_hash=text_hash,
        media_path=str(media_file),
        stored_media_hash=media_hash,
        source_platform="telegram",
        channel_identifier="neutral_channel_c",
        source_message_id=1001,
        post_timestamp=now,
        stored_evidence_hash=ev_hash_with_media,
        has_media=True,
        stored_provenance_status="verified_hashes",
    )
    assert verified["verification_status"] == "verified"
    assert verified["overall_match"] is True
    assert verified["provenance_status"] == "verified_hashes"

    # 2. Missing media -> unavailable (never verified)
    missing_media = verify_record_hashes(
        raw_text=text,
        stored_original_text_hash=text_hash,
        media_path=None,
        stored_media_hash=None,
        source_platform="telegram",
        channel_identifier="neutral_channel_c",
        source_message_id=1001,
        post_timestamp=now,
        stored_evidence_hash=ev_hash_with_media,
        has_media=True,
        stored_provenance_status="unverifiable_media",
    )
    assert missing_media["verification_status"] == "unavailable"
    assert missing_media["overall_match"] is False
    assert missing_media["provenance_note"] == UNVERIFIABLE_MEDIA_NOTE

    # 3. Purged media (file deleted after hash was stored) -> unavailable
    media_file.unlink()
    purged_media = verify_record_hashes(
        raw_text=text,
        stored_original_text_hash=text_hash,
        media_path=str(media_file),
        stored_media_hash=media_hash,
        source_platform="telegram",
        channel_identifier="neutral_channel_c",
        source_message_id=1001,
        post_timestamp=now,
        stored_evidence_hash=ev_hash_with_media,
        has_media=True,
        stored_provenance_status="unverifiable_media",
    )
    assert purged_media["verification_status"] == "unavailable"
    assert purged_media["overall_match"] is False
    assert purged_media["provenance_note"] == UNVERIFIABLE_MEDIA_NOTE

    # 4. Hash mismatch
    ev_hash_text_only = compute_evidence_hash(
        source_platform="telegram",
        channel_identifier="neutral_channel_c",
        source_message_id=1002,
        post_timestamp=now,
        original_text_hash=text_hash,
        media_hashes=[],
    )
    mismatch = verify_record_hashes(
        raw_text="tampered neutral sample message",
        stored_original_text_hash=text_hash,
        media_path=None,
        stored_media_hash=None,
        source_platform="telegram",
        channel_identifier="neutral_channel_c",
        source_message_id=1002,
        post_timestamp=now,
        stored_evidence_hash=ev_hash_text_only,
        has_media=False,
        stored_provenance_status="hash_backfilled",
    )
    assert mismatch["verification_status"] == "mismatch"
    assert mismatch["overall_match"] is False

    # 5. Missing historical hashes -> not_backfilled
    not_backfilled = verify_record_hashes(
        raw_text=text,
        stored_original_text_hash=text_hash,
        media_path=None,
        stored_media_hash=None,
        source_platform="telegram",
        channel_identifier="neutral_channel_c",
        source_message_id=1003,
        post_timestamp=now,
        stored_evidence_hash=None,
        has_media=False,
        stored_provenance_status=None,
    )
    assert not_backfilled["verification_status"] == "not_backfilled"
    assert not_backfilled["overall_match"] is False


@pytest.mark.asyncio
async def test_provenance_api_and_raw_content_protection(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "API_ACCESS_TOKEN", "stage-c-test-token")

    now = datetime(2026, 11, 25, 11, 0, 0, tzinfo=timezone.utc)
    text = "neutral test post for provenance api"
    t_hash = compute_original_text_hash(text)

    async with session_factory() as db:
        ch = Channel(username="neutral_prov_chan", title="Neutral Provenance Channel", is_active=True)
        db.add(ch)
        await db.flush()

        msg = Message(
            channel_id=ch.id,
            telegram_msg_id=501,
            text=text,
            has_media=True,
            media_path=None,
            original_text_hash=t_hash,
            media_hash=None,
            evidence_hash=None,
            provenance_status="unverifiable_media",
            created_at=now,
        )
        db.add(msg)
        await db.flush()

        alert = Alert(
            message_id=msg.id,
            risk_level="HIGH",
            score=0.88,
            categories="cat_a",
            lifecycle_state="active",
        )
        db.add(alert)

        em = EvidenceMessage(
            channel_username="neutral_prov_chan",
            telegram_message_id=501,
            message_timestamp=now,
            raw_text=text,
            original_text_hash=t_hash,
            evidence_hash=None,
            provenance_status="unverifiable_media",
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(em)
        await db.commit()
        alert_id = alert.id
        msg_id = msg.id
        em_id = em.id

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Unauthenticated /alerts/ hides raw text/media but keeps provenance status & note
            r_unauth = await client.get("/alerts/")
            assert r_unauth.status_code == 200
            data_unauth = r_unauth.json()
            assert len(data_unauth) == 1
            assert data_unauth[0]["message"]["text"] is None
            assert data_unauth[0]["message"]["raw_content_redacted"] is True
            assert data_unauth[0]["message"]["provenance_status"] == "unverifiable_media"
            assert data_unauth[0]["message"]["provenance_note"] == UNVERIFIABLE_MEDIA_NOTE

            # Authorized /alerts/{id} returns raw text + provenance status & note
            headers = {"X-API-Key": "stage-c-test-token"}
            r_auth = await client.get(f"/alerts/{alert_id}", headers=headers)
            assert r_auth.status_code == 200
            data_auth = r_auth.json()
            assert data_auth["message"]["text"] == text
            assert data_auth["message"]["provenance_status"] == "unverifiable_media"
            assert data_auth["message"]["provenance_note"] == UNVERIFIABLE_MEDIA_NOTE

            # Authorized /evidence/v2/messages/{id}
            r_ev = await client.get(f"/evidence/v2/messages/{em_id}", headers=headers)
            assert r_ev.status_code == 200
            assert r_ev.json()["provenance_status"] == "unverifiable_media"
            assert r_ev.json()["provenance_note"] == UNVERIFIABLE_MEDIA_NOTE

            # Unauthenticated /evidence/v2/messages/ denied
            r_ev_unauth = await client.get("/evidence/v2/messages/")
            assert r_ev_unauth.status_code == 401

            # Governance verify endpoints report unavailable for unverifiable_media
            r_ver_msg = await client.get(f"/governance/verify/message/{msg_id}", headers=headers)
            assert r_ver_msg.status_code == 200
            assert r_ver_msg.json()["verification_status"] == "unavailable"
            assert r_ver_msg.json()["provenance_note"] == UNVERIFIABLE_MEDIA_NOTE

            r_ver_em = await client.get(f"/governance/verify/evidence/{em_id}", headers=headers)
            assert r_ver_em.status_code == 200
            assert r_ver_em.json()["verification_status"] == "not_backfilled"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_pdf_dossier_renders_unverifiable_media_notice():
    pdf_bytes = generate_channel_dossier_pdf(
        {
            "username": "neutral_pdf_chan",
            "title": "Neutral PDF Channel",
            "risk_level": "HIGH",
            "avg_score": 0.9,
            "messages_scanned": 10,
            "flagged_count": 1,
            "high_count": 1,
            "medium_count": 0,
            "top_categories": ["cat_a"],
            "top_identifiers": [],
            "connected_nodes": {},
            "sample_messages": [
                {
                    "id": 1,
                    "score": 0.9,
                    "risk_level": "HIGH",
                    "date": "2026-11-25T10:00:00",
                    "matched_terms": ["neutral_term"],
                    "text": "neutral sample intercept",
                    "provenance_status": "unverifiable_media",
                    "provenance_note": UNVERIFIABLE_MEDIA_NOTE,
                    "evidence_hash": "a" * 64,
                }
            ],
        }
    )
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000

