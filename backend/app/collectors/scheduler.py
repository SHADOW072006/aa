"""
Priority-based channel collection scheduler.

Replaces the sequential per-channel sleep loop in TelegramCollector with
a lightweight scheduler that:
  - Wakes every COLLECTOR_SCHEDULER_INTERVAL seconds (default 10)
  - Queries only channels whose next_poll_at <= now (or NULL)
  - Prioritises HIGH > MEDIUM > LOW tier channels
  - Runs at most COLLECTOR_MAX_CONCURRENT collections in parallel
  - Updates next_poll_at after each collection (success or failure)
  - Handles FloodWaitError, ChannelPrivateError, UsernameInvalidError
  - Records health events and updates channel_status correctly

Requirements: Req 1–5
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Set

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from app.core.config import settings
from app.db.crud import (
    get_due_channels,
    record_health_event,
    update_channel_next_poll,
)
from app.db.database import get_session

logger = logging.getLogger(__name__)

# Poll tier -> interval in seconds
_TIER_INTERVAL = {
    "HIGH": settings.POLL_INTERVAL_HIGH,
    "MEDIUM": settings.POLL_INTERVAL_MEDIUM,
    "LOW": settings.POLL_INTERVAL_LOW,
}


class ChannelScheduler:
    """
    Lightweight priority scheduler for the continuous channel monitor.

    Usage::

        scheduler = ChannelScheduler(client)
        await scheduler.run_forever()   # long-running task
    """

    def __init__(self, client: TelegramClient) -> None:
        self.client = client
        self._running = False
        self._semaphore = asyncio.Semaphore(settings.COLLECTOR_MAX_CONCURRENT)
        self._running_ids: Set[int] = set()   # channel IDs currently being collected

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        self._running = True
        logger.info(
            "ChannelScheduler started (interval=%ds, max_concurrent=%d)",
            settings.COLLECTOR_SCHEDULER_INTERVAL,
            settings.COLLECTOR_MAX_CONCURRENT,
        )
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.error("Scheduler tick error: %s", exc, exc_info=True)
            await asyncio.sleep(settings.COLLECTOR_SCHEDULER_INTERVAL)

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Scheduler tick — dispatches due channels up to concurrency limit
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        """Single scheduler tick: query due channels and dispatch tasks."""
        now = datetime.utcnow()
        # Fetch more than MAX_CONCURRENT so we can skip already-running ones
        fetch_limit = settings.COLLECTOR_MAX_CONCURRENT * 4

        async with get_session() as db:
            due = await get_due_channels(db, now=now, limit=fetch_limit)

        dispatched = 0
        for channel in due:
            if channel.id in self._running_ids:
                continue   # already in-flight
            slots_available = settings.COLLECTOR_MAX_CONCURRENT - len(self._running_ids)
            if slots_available <= 0:
                break
            # Fire-and-forget: do not await, just schedule the task
            self._running_ids.add(channel.id)
            asyncio.create_task(
                self._collect_one_safe(channel.id, channel.username, channel.poll_tier or "LOW")
            )
            dispatched += 1

        if dispatched:
            logger.debug("Scheduler tick: dispatched %d channel(s)", dispatched)

    # ------------------------------------------------------------------
    # Collection task for one channel
    # ------------------------------------------------------------------

    async def _collect_one_safe(
        self, channel_id: int, channel_username: str, poll_tier: str
    ) -> None:
        """Wrapper that always cleans up _running_ids."""
        try:
            async with self._semaphore:
                await self._collect_one(channel_id, channel_username, poll_tier)
        except Exception as exc:
            logger.error(
                "Unhandled error collecting @%s: %s", channel_username, exc, exc_info=True
            )
        finally:
            self._running_ids.discard(channel_id)

    async def _collect_one(
        self, channel_id: int, channel_username: str, poll_tier: str
    ) -> None:
        """
        Collect one channel with backoff and error tracking.

        Success path:
            - Call _collect_channel from TelegramCollector
            - Set next_poll_at = now + tier_interval
            - Reset consecutive_error_count = 0, error_state = False, channel_status = 'active'

        FloodWaitError:
            - next_poll_at = now + max(e.seconds, settings.MIN_BACKOFF) * BACKOFF_MULTIPLIER
            - Capped at MAX_BACKOFF_SECONDS
            - Record health event 'flood_wait'
            - Increment consecutive_error_count (but do NOT set error_state on first flood)

        ChannelPrivateError / UsernameInvalidError / UsernameNotOccupiedError:
            - channel_status = 'inaccessible'
            - next_poll_at = now + ERROR_BACKOFF_SECONDS
            - Record health event

        3+ consecutive errors (any type):
            - channel_status = 'error_state'

        Any other Exception:
            - Treat as a collection error, increment counter, next_poll_at += ERROR_BACKOFF_SECONDS
        """
        from app.collectors.telegram_collector import get_collector
        collector = get_collector()

        now = datetime.utcnow()
        tier_interval = _TIER_INTERVAL.get(poll_tier, settings.POLL_INTERVAL_LOW)

        try:
            # Load fresh channel row
            from sqlalchemy import select
            from app.db.models import Channel
            async with get_session() as db:
                result = await db.execute(select(Channel).where(Channel.id == channel_id))
                channel_row = result.scalar_one_or_none()
            if channel_row is None:
                return

            await collector._collect_channel(channel_row)

            # ── Success ──────────────────────────────────────────────────
            next_poll = now + timedelta(seconds=tier_interval)
            async with get_session() as db:
                await update_channel_next_poll(
                    db,
                    channel_id=channel_id,
                    next_poll_at=next_poll,
                    channel_status="active",
                    consecutive_error_count=0,
                    error_state=False,
                )
            logger.debug(
                "Collected @%s (tier=%s) next_poll_at=%s",
                channel_username, poll_tier, next_poll.isoformat(),
            )

        except FloodWaitError as exc:
            # ── FloodWait ────────────────────────────────────────────────
            raw_wait = max(exc.seconds, settings.MIN_BACKOFF)
            backoff = int(min(raw_wait * settings.BACKOFF_MULTIPLIER, settings.MAX_BACKOFF_SECONDS))
            next_poll = now + timedelta(seconds=backoff)
            logger.warning(
                "FloodWait @%s — deferring %ds (next_poll_at=%s)",
                channel_username, backoff, next_poll.isoformat(),
            )
            async with get_session() as db:
                await record_health_event(
                    db, channel_id, event_type="flood_wait", error_message=str(exc)
                )
                result = await db.execute(
                    select(Channel).where(Channel.id == channel_id)
                )
                ch = result.scalar_one_or_none()
                new_count = (getattr(ch, "consecutive_error_count", 0) or 0) + 1
                await update_channel_next_poll(
                    db,
                    channel_id=channel_id,
                    next_poll_at=next_poll,
                    consecutive_error_count=new_count,
                    error_state=new_count >= settings.ERROR_STATE_THRESHOLD,
                    channel_status="error_state" if new_count >= settings.ERROR_STATE_THRESHOLD else None,
                )

        except (ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError) as exc:
            # ── Inaccessible ─────────────────────────────────────────────
            next_poll = now + timedelta(seconds=settings.ERROR_BACKOFF_SECONDS)
            logger.warning("@%s inaccessible: %s", channel_username, exc)
            async with get_session() as db:
                event = (
                    "private_error" if isinstance(exc, ChannelPrivateError)
                    else "username_invalid"
                )
                await record_health_event(db, channel_id, event_type=event, error_message=str(exc))
                await update_channel_next_poll(
                    db,
                    channel_id=channel_id,
                    next_poll_at=next_poll,
                    channel_status="inaccessible",
                )

        except Exception as exc:
            # ── Generic error ─────────────────────────────────────────────
            next_poll = now + timedelta(seconds=settings.ERROR_BACKOFF_SECONDS)
            logger.error("Error collecting @%s: %s", channel_username, exc, exc_info=True)
            async with get_session() as db:
                await record_health_event(
                    db, channel_id, event_type="collection_error", error_message=str(exc)
                )
                result = await db.execute(
                    select(Channel).where(Channel.id == channel_id)
                )
                ch = result.scalar_one_or_none()
                new_count = (getattr(ch, "consecutive_error_count", 0) or 0) + 1
                await update_channel_next_poll(
                    db,
                    channel_id=channel_id,
                    next_poll_at=next_poll,
                    consecutive_error_count=new_count,
                    error_state=new_count >= settings.ERROR_STATE_THRESHOLD,
                    channel_status="error_state" if new_count >= settings.ERROR_STATE_THRESHOLD else None,
                )


_scheduler: Optional[ChannelScheduler] = None


def get_scheduler(client: TelegramClient) -> ChannelScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ChannelScheduler(client)
    return _scheduler
