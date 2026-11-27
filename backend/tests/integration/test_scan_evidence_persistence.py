"""
Integration tests for scan evidence persistence.

Exercises the full CRUD → DB round-trip using an in-memory async SQLite
database (aiosqlite).  No mocks — real SQLAlchemy sessions and real model
rows are used throughout.

Requirements: 3.2, 4.2, 5.4, 7.9, 17.4
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

from app.db.models import (
    Base,
    Channel,
    ChannelScanResult,
    ScanJob,
    ScanEvidence,
    PivotCandidate,
    ChannelScoreComponents,
)
from app.db import crud


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """Fresh in-memory async SQLite session for each test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _make_scan_job(db: AsyncSession) -> ScanJob:
    """Helper: insert a minimal ScanJob row and return it."""
    job = ScanJob(seed_terms='["test"]', status="pending")
    db.add(job)
    await db.flush()
    return job


async def _make_channel_scan_result(db: AsyncSession, scan_job: ScanJob) -> ChannelScanResult:
    """Helper: insert a minimal ChannelScanResult row and return it."""
    result = ChannelScanResult(
        scan_job_id=scan_job.id,
        channel_username="@result_channel",
        seed_term="test",
    )
    db.add(result)
    await db.flush()
    return result


async def _make_channel(db: AsyncSession, username: str = "@health_chan") -> Channel:
    """Helper: insert a minimal Channel row and return it."""
    channel = Channel(username=username)
    db.add(channel)
    await db.flush()
    return channel


# ---------------------------------------------------------------------------
# 1. upsert_scan_evidence creates a new row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_scan_evidence_creates_new(db: AsyncSession) -> None:
    job = await _make_scan_job(db)

    evidence = await crud.upsert_scan_evidence(
        db,
        channel_username="@test",
        telegram_message_id=1,
        scan_job_id=job.id,
        classifier_score=0.8,
        risk_level="high",
        severity_tier="P2",
    )

    assert evidence.id is not None
    assert evidence.classifier_score == pytest.approx(0.8)
    assert evidence.channel_username == "@test"
    assert evidence.telegram_message_id == 1


# ---------------------------------------------------------------------------
# 2. upsert_scan_evidence is idempotent — no duplicate rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_scan_evidence_is_idempotent(db: AsyncSession) -> None:
    job = await _make_scan_job(db)

    await crud.upsert_scan_evidence(
        db,
        channel_username="@test",
        telegram_message_id=1,
        scan_job_id=job.id,
        classifier_score=0.5,
        risk_level="medium",
        severity_tier="P3",
    )
    await crud.upsert_scan_evidence(
        db,
        channel_username="@test",
        telegram_message_id=1,
        scan_job_id=job.id,
        classifier_score=0.5,
        risk_level="medium",
        severity_tier="P3",
    )

    rows = (await db.execute(select(ScanEvidence))).scalars().all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# 3. Second call updates classifier_score on existing row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_scan_evidence_updates_on_second_call(db: AsyncSession) -> None:
    job = await _make_scan_job(db)

    await crud.upsert_scan_evidence(
        db,
        channel_username="@test",
        telegram_message_id=42,
        scan_job_id=job.id,
        classifier_score=0.5,
        risk_level="medium",
        severity_tier="P3",
    )
    updated = await crud.upsert_scan_evidence(
        db,
        channel_username="@test",
        telegram_message_id=42,
        scan_job_id=job.id,
        classifier_score=0.9,
        risk_level="high",
        severity_tier="P1",
    )

    assert updated.classifier_score == pytest.approx(0.9)
    # Confirm only one row exists
    rows = (await db.execute(select(ScanEvidence))).scalars().all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# 4. upsert_pivot_candidate creates row with correct defaults
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_candidate_upsert(db: AsyncSession) -> None:
    candidate = await crud.upsert_pivot_candidate(
        db,
        source_channel_username="@test",
        candidate_type="phone",
        candidate_value="+79001234567",
    )

    assert candidate.id is not None
    assert candidate.status == "pending"
    assert candidate.candidate_value == "+79001234567"
    assert candidate.candidate_type == "phone"


# ---------------------------------------------------------------------------
# 5. upsert_pivot_candidate is idempotent — no duplicate rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pivot_candidate_idempotent(db: AsyncSession) -> None:
    for _ in range(2):
        await crud.upsert_pivot_candidate(
            db,
            source_channel_username="@test",
            candidate_type="phone",
            candidate_value="+79001234567",
        )

    rows = (await db.execute(select(PivotCandidate))).scalars().all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# 6. record_health_event and get_health_events round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_health_event(db: AsyncSession) -> None:
    channel = await _make_channel(db)

    await crud.record_health_event(
        db,
        channel_id=channel.id,
        event_type="flood_wait",
        error_message="Too many requests",
    )

    events = await crud.get_health_events(db, channel_id=channel.id)
    assert len(events) == 1
    assert events[0].event_type == "flood_wait"
    assert events[0].error_message == "Too many requests"
    assert events[0].channel_id == channel.id


# ---------------------------------------------------------------------------
# 7. record_disposition_change and get_disposition_history round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_disposition_history(db: AsyncSession) -> None:
    await crud.record_disposition_change(
        db,
        target_type="alert",
        target_id=1,
        previous_disposition=None,
        new_disposition="confirmed_threat",
        changed_by="analyst1",
    )

    history = await crud.get_disposition_history(db, "alert", 1)
    assert len(history) == 1
    assert history[0].new_disposition == "confirmed_threat"
    assert history[0].target_type == "alert"
    assert history[0].target_id == 1
    assert history[0].changed_by == "analyst1"
    assert history[0].previous_disposition is None


# ---------------------------------------------------------------------------
# 8. upsert_channel_score creates row with correct composite_score
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_channel_score_upsert(db: AsyncSession) -> None:
    job = await _make_scan_job(db)
    result = await _make_channel_scan_result(db, job)

    score = await crud.upsert_channel_score(
        db,
        channel_scan_result_id=result.id,
        composite_score=0.75,
        max_message_score=0.9,
        high_confidence_message_count=3,
        distinct_incident_count=1,
        recency_weight=1.0,
        identifier_density=0.5,
        valid_pivot_count=2,
        analyst_confirmation_signal=0.0,
    )

    assert score.id is not None
    assert score.composite_score == pytest.approx(0.75)
    assert score.max_message_score == pytest.approx(0.9)
    assert score.high_confidence_message_count == 3
    assert score.channel_scan_result_id == result.id
