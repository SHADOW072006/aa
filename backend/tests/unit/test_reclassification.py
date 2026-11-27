"""
Stage 2 unit tests: historical reclassification, dry-run, idempotency,
resume behaviour, prior-observation preservation, and no duplicate alert creation.
Uses minimal neutral placeholder strings only.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.classifiers.lexicon_loader import init_lexicons
from app.core.config import settings
from app.db.models import (
    Alert,
    Base,
    Channel,
    EvidenceMessage,
    EvidenceObservation,
    Message,
)
from app.services.reclassification_service import run_reclassification


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


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def _factory():
        async with Session() as s:
            yield s
            await s.commit()

    yield _factory, Session
    await engine.dispose()


async def _seed_legacy_messages(Session) -> tuple[int, int]:
    async with Session() as s:
        ch = Channel(username="placeholder_reclass_ch", is_active=True)
        s.add(ch)
        await s.flush()

        # Msg 1: legacy investment_fraud alert (should drop to LOW under illegal_trade)
        m1 = Message(
            channel_id=ch.id,
            telegram_msg_id=101,
            text="colour prediction group guaranteed return investment",
            created_at=datetime(2025, 1, 1, 10, 0, 0),
            source="telegram",
        )
        # Msg 2: core illegal-trade message (should remain/become HIGH)
        m2 = Message(
            channel_id=ch.id,
            telegram_msg_id=102,
            text="heroin available for sale dm me @placeholder_dealer",
            created_at=datetime(2025, 1, 1, 10, 5, 0),
            source="telegram",
        )
        # Msg 3: neutral unflagged message
        m3 = Message(
            channel_id=ch.id,
            telegram_msg_id=103,
            text="hello everyone good morning placeholder",
            created_at=datetime(2025, 1, 1, 10, 10, 0),
            source="telegram",
        )
        s.add_all([m1, m2, m3])
        await s.flush()

        a1 = Alert(
            message_id=m1.id,
            risk_level="HIGH",
            score=0.90,
            categories="investment_fraud,colour_trading_scam",
            evidence='{"scoring_version":"legacy_v1"}',
            is_reviewed=True,
            reviewed_by="analyst_a",
            disposition="false_positive",
        )
        s.add(a1)
        em1 = EvidenceMessage(
            channel_username=ch.username,
            telegram_message_id=101,
            raw_text=m1.text,
        )
        s.add(em1)
        await s.flush()
        obs1 = EvidenceObservation(
            evidence_message_id=em1.id,
            source_type="continuous_monitor",
            classifier_version="legacy_v1",
            score=0.90,
            risk_level="HIGH",
            severity_tier="P2",
        )
        s.add(obs1)
        await s.commit()
        return m1.id, m2.id


@pytest.mark.asyncio
async def test_dry_run_makes_no_writes(session_factory):
    factory, Session = session_factory
    await _seed_legacy_messages(Session)

    res = await run_reclassification(factory, actor="analyst_a", dry_run=True, batch_size=10)
    assert res["dry_run"] is True
    assert res["processed"] == 3
    assert res["no_longer_flagged"] == 1
    assert res["newly_flagged"] == 1

    async with Session() as s:
        obs_cnt = (await s.execute(select(func.count(EvidenceObservation.id)))).scalar_one()
        alert_cnt = (await s.execute(select(func.count(Alert.id)))).scalar_one()
        assert obs_cnt == 1  # unchanged
        assert alert_cnt == 1  # unchanged


@pytest.mark.asyncio
async def test_live_reclassification_preserves_prior_obs_and_is_idempotent(session_factory):
    factory, Session = session_factory
    m1_id, m2_id = await _seed_legacy_messages(Session)

    res1 = await run_reclassification(factory, actor="analyst_a", dry_run=False, batch_size=10)
    assert res1["processed"] == 3
    assert res1["no_longer_flagged"] == 1
    assert res1["newly_flagged"] == 1
    assert res1["failed"] == 0

    async with Session() as s:
        # Prior legacy_v1 observation still exists + new intent_v2 observations added
        obs_all = (await s.execute(select(EvidenceObservation))).scalars().all()
        assert len(obs_all) == 4  # 1 legacy + 3 new
        assert any(o.classifier_version == "legacy_v1" for o in obs_all)

        # No duplicate alerts for m1 or m2; disposition preserved on m1
        alerts = (await s.execute(select(Alert))).scalars().all()
        assert len(alerts) == 2
        a1 = next(a for a in alerts if a.message_id == m1_id)
        assert a1.risk_level == "LOW"
        assert a1.disposition == "false_positive"
        assert a1.is_reviewed is True

    # Re-running must be idempotent (all 3 skipped, 0 new observations)
    res2 = await run_reclassification(factory, actor="analyst_a", dry_run=False, batch_size=10)
    assert res2["skipped"] == 3
    assert res2["processed"] == 0


@pytest.mark.asyncio
async def test_resume_behaviour(session_factory):
    factory, Session = session_factory
    await _seed_legacy_messages(Session)

    # Run only 1 batch of size 2 (processes 2 of 3 messages)
    p1 = await run_reclassification(factory, actor="analyst_a", dry_run=False, batch_size=2, max_batches=1)
    assert p1["status"] == "paused"
    assert p1["processed"] == 2

    # Resume from paused job -> processes remaining 1 message and finishes
    p2 = await run_reclassification(
        factory, actor="analyst_a", dry_run=False, batch_size=2, resume_job_id=p1["job_id"]
    )
    assert p2["status"] == "done"
    assert p2["processed"] == 3
    assert p2["skipped"] == 0


@pytest.mark.asyncio
async def test_concurrent_start_rejection_and_stale_recovery(session_factory):
    from datetime import timedelta
    from app.db.models import AuditLog, ReclassificationJob
    from app.services.reclassification_service import (
        ActiveReclassificationJobError,
        recover_stale_reclassification_job,
    )

    factory, Session = session_factory
    await _seed_legacy_messages(Session)

    # Insert an active running job with fresh heartbeat
    async with Session() as s:
        j_active = ReclassificationJob(
            scoring_version="intent_v2",
            status="running",
            dry_run=False,
            last_processed_message_id=1,
            total_messages=3,
            processed_count=1,
            started_by="worker_1",
            heartbeat_at=datetime.utcnow(),
        )
        s.add(j_active)
        await s.commit()
        active_id = j_active.id

    # Attempting a second live non-dry-run job must be rejected with active_job info
    with pytest.raises(ActiveReclassificationJobError) as exc_info:
        await run_reclassification(factory, actor="worker_2", dry_run=False, batch_size=2)
    assert exc_info.value.active_job["job_id"] == active_id
    assert exc_info.value.active_job["processed"] == 1

    # Fresh heartbeat cannot be force-recovered
    async with Session() as s:
        with pytest.raises(ValueError, match="recent heartbeat"):
            await recover_stale_reclassification_job(
                s, job_id=active_id, actor="op_a", confirm=True, target_status="interrupted"
            )

    # Make heartbeat stale -> confirm=False still rejected, confirm=True succeeds + audit-logged
    async with Session() as s:
        j = (await s.execute(select(ReclassificationJob).where(ReclassificationJob.id == active_id))).scalar_one()
        j.heartbeat_at = datetime.utcnow() - timedelta(hours=2)
        await s.commit()

    async with Session() as s:
        with pytest.raises(ValueError, match="confirmation"):
            await recover_stale_reclassification_job(
                s, job_id=active_id, actor="op_a", confirm=False, target_status="interrupted"
            )
        recovered = await recover_stale_reclassification_job(
            s, job_id=active_id, actor="op_a", confirm=True, target_status="superseded", reason="stale worker"
        )
        assert recovered["status"] == "superseded"
        logs = (await s.execute(select(AuditLog).where(AuditLog.action == "reclassification_job_recover"))).scalars().all()
        assert len(logs) == 1
        assert logs[0].target_id == active_id
        await s.commit()


