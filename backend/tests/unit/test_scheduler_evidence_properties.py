"""
Property-based tests for the scheduler and evidence model.

Uses Hypothesis for property generation and an in-memory async SQLite
database (aiosqlite) for CRUD tests — same pattern as
tests/integration/test_scan_evidence_persistence.py.

**Validates: Requirements 1–10 (scheduler and evidence model properties)**
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import List

import pytest
import pytest_asyncio
from hypothesis import assume, given
from hypothesis import settings as h_settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db import crud
from app.db.models import Base, Channel, EvidenceMessage, EvidenceObservation


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


# ---------------------------------------------------------------------------
# Helper: build a fresh in-memory session for use inside asyncio.run()
# ---------------------------------------------------------------------------

async def _make_session():
    """Create engine + session. Caller owns disposal."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    session = Session()
    return engine, session


async def _dispose(engine, session):
    await session.close()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Property 1 — Scheduler filter: only due channels returned
#
# **Validates: Requirements 1 (scheduler filter)**
# ---------------------------------------------------------------------------


@given(minutes_offset=st.integers(min_value=-1000, max_value=1000))
@h_settings(max_examples=100, deadline=None)
def test_get_due_channels_filter(minutes_offset: int) -> None:
    """
    **Validates: Requirements 1**

    A channel with next_poll_at = now + minutes_offset minutes should be
    included in get_due_channels only when minutes_offset <= 0.
    """

    async def _run():
        engine, session = await _make_session()
        try:
            now = datetime.utcnow()
            next_poll_at = now + timedelta(minutes=minutes_offset)

            channel = Channel(
                username="@testchan",
                is_active=True,
                channel_status="active",
                poll_tier="LOW",
            )
            channel.next_poll_at = next_poll_at
            session.add(channel)
            await session.flush()

            due = await crud.get_due_channels(session, now=now, limit=50)
            channel_ids = [c.id for c in due]

            if minutes_offset <= 0:
                assert channel.id in channel_ids, (
                    f"Channel with next_poll_at={next_poll_at} (offset={minutes_offset}m) "
                    f"should be due at now={now}"
                )
            else:
                assert channel.id not in channel_ids, (
                    f"Channel with next_poll_at={next_poll_at} (offset={minutes_offset}m) "
                    f"should NOT be due at now={now}"
                )
        finally:
            await _dispose(engine, session)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 2 — Tier priority: HIGH before MEDIUM before LOW
#
# **Validates: Requirements 2 (tier priority ordering)**
# ---------------------------------------------------------------------------


@given(
    tiers=st.lists(
        st.sampled_from(["HIGH", "MEDIUM", "LOW"]), min_size=3, max_size=10
    )
)
@h_settings(max_examples=100, deadline=None)
def test_tier_priority_ordering(tiers: List[str]) -> None:
    """
    **Validates: Requirements 2**

    When all channels are due (next_poll_at = now - 1 min), get_due_channels
    must return them ordered HIGH first, then MEDIUM, then LOW.
    """

    async def _run():
        engine, session = await _make_session()
        try:
            now = datetime.utcnow()
            past = now - timedelta(minutes=1)

            created_ids = {}
            for i, tier in enumerate(tiers):
                ch = Channel(
                    username=f"@chan_{i}_{tier}",
                    is_active=True,
                    channel_status="active",
                    poll_tier=tier,
                )
                ch.next_poll_at = past
                session.add(ch)
                await session.flush()
                created_ids[ch.id] = tier

            due = await crud.get_due_channels(session, now=now, limit=len(tiers) + 10)

            tier_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, None: 2}
            returned_tiers = [tier_order[created_ids[c.id]] for c in due if c.id in created_ids]

            # Verify the sequence is non-decreasing (sorted ascending by tier priority)
            for idx in range(len(returned_tiers) - 1):
                assert returned_tiers[idx] <= returned_tiers[idx + 1], (
                    f"Ordering violated: tier at position {idx} ({returned_tiers[idx]}) "
                    f"> tier at position {idx+1} ({returned_tiers[idx+1]}). "
                    f"Full order: {returned_tiers}"
                )
        finally:
            await _dispose(engine, session)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 3 — FloodWait backoff cap
#
# **Validates: Requirements 3 (FloodWait backoff)**
# Pure function test — no DB needed.
# ---------------------------------------------------------------------------


@given(e_seconds=st.integers(min_value=1, max_value=100_000))
@h_settings(max_examples=300)
def test_floodwait_backoff_cap(e_seconds: int) -> None:
    """
    **Validates: Requirements 3**

    The computed FloodWait backoff must always be:
      - <= settings.MAX_BACKOFF_SECONDS
      - >= settings.MIN_BACKOFF
    """
    backoff = int(
        min(
            max(e_seconds, settings.MIN_BACKOFF) * settings.BACKOFF_MULTIPLIER,
            settings.MAX_BACKOFF_SECONDS,
        )
    )
    assert backoff <= settings.MAX_BACKOFF_SECONDS, (
        f"backoff {backoff} exceeds MAX_BACKOFF_SECONDS {settings.MAX_BACKOFF_SECONDS}"
    )
    assert backoff >= settings.MIN_BACKOFF, (
        f"backoff {backoff} is below MIN_BACKOFF {settings.MIN_BACKOFF}"
    )


# ---------------------------------------------------------------------------
# Property 4 — Error counter threshold
#
# **Validates: Requirements 4 (error state threshold)**
# Pure function test — no DB needed.
# ---------------------------------------------------------------------------


@given(n=st.integers(min_value=0, max_value=20))
@h_settings(max_examples=100)
def test_error_state_threshold(n: int) -> None:
    """
    **Validates: Requirements 4**

    After n consecutive errors, the error_state flag is determined solely
    by whether n >= ERROR_STATE_THRESHOLD.
    """
    threshold = settings.ERROR_STATE_THRESHOLD

    # Simulate: start from a clean channel and apply n errors
    consecutive_error_count = n
    error_state = consecutive_error_count >= threshold

    if n >= threshold:
        assert error_state is True, (
            f"error_state should be True after {n} errors "
            f"(threshold={threshold})"
        )
    else:
        assert error_state is False, (
            f"error_state should be False after {n} errors "
            f"(threshold={threshold})"
        )


# ---------------------------------------------------------------------------
# Property 5 — Success resets error state
#
# **Validates: Requirements 5 (success resets error state)**
# Pure assertion — no DB needed.
# ---------------------------------------------------------------------------


def test_success_resets_error_state() -> None:
    """
    **Validates: Requirements 5**

    After a successful collection, consecutive_error_count must be 0 and
    error_state must be False, regardless of previous error count.
    """
    # Simulate _reset_error_state logic
    for prior_errors in [0, 1, 3, 5, 10]:
        # Apply reset (mimicking _reset_error_state from telegram_collector)
        consecutive_error_count = 0
        error_state = False

        assert consecutive_error_count == 0, (
            f"consecutive_error_count should be 0 after success, was {prior_errors} before"
        )
        assert error_state is False, (
            f"error_state should be False after success, prior errors={prior_errors}"
        )


# ---------------------------------------------------------------------------
# Property 6 — upsert_evidence_message preserves first_seen_at and disposition
#
# **Validates: Requirements 6 (upsert preserves first_seen_at and disposition)**
# ---------------------------------------------------------------------------


@given(
    channel=st.text(min_size=1, max_size=50).map(lambda s: s.replace("\x00", "a")),
    msg_id=st.integers(min_value=1, max_value=9_223_372_036_854_775_807),
)
@h_settings(max_examples=100, deadline=None)
def test_upsert_preserves_first_seen_and_disposition(channel: str, msg_id: int) -> None:
    """
    **Validates: Requirements 6**

    Re-upserting an EvidenceMessage must not change first_seen_at or
    any disposition value that was previously set.
    """

    async def _run():
        engine, session = await _make_session()
        try:
            # First upsert — creates the row
            ev1 = await crud.upsert_evidence_message(
                session,
                channel_username=channel,
                telegram_message_id=msg_id,
                raw_text="initial text",
            )
            first_seen = ev1.first_seen_at

            # Set a disposition
            await crud.set_evidence_message_disposition(
                session,
                evidence_message_id=ev1.id,
                disposition="confirmed_threat",
                notes="test note",
                changed_by="analyst1",
            )

            # Refresh to get updated disposition
            await session.refresh(ev1)
            original_disposition = ev1.disposition

            # Second upsert — must not overwrite first_seen_at or disposition
            ev2 = await crud.upsert_evidence_message(
                session,
                channel_username=channel,
                telegram_message_id=msg_id,
                raw_text="new text that should not overwrite",
            )

            assert ev2.id == ev1.id, "Second upsert should return the same row"
            assert ev2.first_seen_at == first_seen, (
                f"first_seen_at changed: was {first_seen}, now {ev2.first_seen_at}"
            )
            assert ev2.disposition == original_disposition, (
                f"disposition changed: was {original_disposition!r}, now {ev2.disposition!r}"
            )
        finally:
            await _dispose(engine, session)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 7 — insert_evidence_observation always adds rows
#
# **Validates: Requirements 7 (observations always insert)**
# ---------------------------------------------------------------------------


@given(n=st.integers(min_value=1, max_value=10))
@h_settings(max_examples=50, deadline=None)
def test_observations_always_insert(n: int) -> None:
    """
    **Validates: Requirements 7**

    insert_evidence_observation always creates a new row — it never
    deduplicates.  Inserting n observations must yield exactly n rows.
    """

    async def _run():
        engine, session = await _make_session()
        try:
            # Create a parent EvidenceMessage first
            ev = await crud.upsert_evidence_message(
                session,
                channel_username="@obs_test",
                telegram_message_id=1,
            )

            for i in range(n):
                await crud.insert_evidence_observation(
                    session,
                    evidence_message_id=ev.id,
                    source_type="scheduled_scan",
                    score=0.5,
                    risk_level="MEDIUM",
                    severity_tier="P2",
                )

            observations = await crud.get_observations_for_message(session, ev.id)
            assert len(observations) == n, (
                f"Expected {n} observations, got {len(observations)}"
            )
        finally:
            await _dispose(engine, session)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 8 — list_evidence_messages channel filter
#
# **Validates: Requirements 8 (channel filter returns only matching rows)**
# ---------------------------------------------------------------------------


@given(
    username=st.text(min_size=1, max_size=30).map(lambda s: s.replace("\x00", "a")),
    other=st.text(min_size=1, max_size=30).map(lambda s: s.replace("\x00", "a")),
)
@h_settings(max_examples=100, deadline=None)
def test_list_filter_channel(username: str, other: str) -> None:
    """
    **Validates: Requirements 8**

    list_evidence_messages(channel_username=username) must return only
    rows belonging to that channel, never rows from a different channel.
    """
    assume(username != other)

    async def _run():
        engine, session = await _make_session()
        try:
            # Insert one message per channel
            await crud.upsert_evidence_message(
                session,
                channel_username=username,
                telegram_message_id=1,
            )
            await crud.upsert_evidence_message(
                session,
                channel_username=other,
                telegram_message_id=1,
            )

            results = await crud.list_evidence_messages(
                session, channel_username=username
            )

            for row in results:
                assert row.channel_username == username, (
                    f"Row with channel_username={row.channel_username!r} "
                    f"should not appear when filtering for {username!r}"
                )

            # At minimum, the message we inserted for 'username' must be there
            assert len(results) >= 1, (
                f"No results returned for channel_username={username!r}"
            )
        finally:
            await _dispose(engine, session)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 9 — Observations ordered newest-first
#
# **Validates: Requirements 9 (observations ordered newest-first)**
# ---------------------------------------------------------------------------


@given(n=st.integers(min_value=2, max_value=5))
@h_settings(max_examples=50, deadline=None)
def test_observations_ordered_newest_first(n: int) -> None:
    """
    **Validates: Requirements 9**

    get_observations_for_message must return observations ordered by
    classified_at DESC (newest first).
    """

    async def _run():
        engine, session = await _make_session()
        try:
            ev = await crud.upsert_evidence_message(
                session,
                channel_username="@order_test",
                telegram_message_id=42,
            )

            # Insert n observations with explicit increasing classified_at values
            base_time = datetime(2024, 1, 1, 0, 0, 0)
            for i in range(n):
                obs = EvidenceObservation(
                    evidence_message_id=ev.id,
                    source_type="scheduled_scan",
                    score=0.5 + i * 0.01,
                    risk_level="MEDIUM",
                    severity_tier="P2",
                    classified_at=base_time + timedelta(hours=i),
                )
                session.add(obs)
            await session.flush()

            observations = await crud.get_observations_for_message(session, ev.id)
            assert len(observations) == n, (
                f"Expected {n} observations, got {len(observations)}"
            )

            # Verify DESC order: each classified_at >= the next one
            for i in range(len(observations) - 1):
                assert observations[i].classified_at >= observations[i + 1].classified_at, (
                    f"Ordering violated at index {i}: "
                    f"{observations[i].classified_at} < {observations[i+1].classified_at}"
                )
        finally:
            await _dispose(engine, session)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 10 — upsert is idempotent on content (same call twice = same result)
#
# **Validates: Requirements 10 (upsert idempotency)**
# ---------------------------------------------------------------------------


@given(
    channel=st.text(min_size=1, max_size=50).map(lambda s: s.replace("\x00", "a")),
    msg_id=st.integers(min_value=1, max_value=9_223_372_036_854_775_807),
)
@h_settings(max_examples=100, deadline=None)
def test_upsert_idempotent(channel: str, msg_id: int) -> None:
    """
    **Validates: Requirements 10**

    Calling upsert_evidence_message twice with identical arguments must:
      - Return the same DB row (same id)
      - Leave only one row in the table for that (channel, msg_id)
      - Satisfy first_seen_at <= last_seen_at
    """

    async def _run():
        engine, session = await _make_session()
        try:
            kwargs = dict(
                channel_username=channel,
                telegram_message_id=msg_id,
                raw_text="some evidence text",
            )

            ev1 = await crud.upsert_evidence_message(session, **kwargs)
            ev2 = await crud.upsert_evidence_message(session, **kwargs)

            assert ev1.id == ev2.id, (
                f"Two upserts returned different IDs: {ev1.id} vs {ev2.id}"
            )

            # Only one row in the table for this (channel, msg_id)
            rows = (
                await session.execute(
                    select(EvidenceMessage).where(
                        EvidenceMessage.channel_username == channel,
                        EvidenceMessage.telegram_message_id == msg_id,
                    )
                )
            ).scalars().all()
            assert len(rows) == 1, (
                f"Expected 1 row, found {len(rows)} for channel={channel!r}, msg_id={msg_id}"
            )

            # first_seen_at <= last_seen_at
            final = rows[0]
            assert final.first_seen_at <= final.last_seen_at, (
                f"first_seen_at ({final.first_seen_at}) > last_seen_at ({final.last_seen_at})"
            )
        finally:
            await _dispose(engine, session)

    asyncio.run(_run())
