"""
Automatic channel discovery engine.

How it works
------------
1. Every DISCOVERY_INTERVAL_SECONDS seconds, the engine runs a Telegram
   global search for each seed term in the discovery seed list.
2. For each found channel/group that is not already in the watchlist:
   a. Fetch up to DISCOVERY_MIN_MESSAGES_TO_SCORE recent messages.
   b. Run the classifier on each message.
   c. If the average score across those messages >= DISCOVERY_MIN_SCORE_TO_ADD,
      automatically add the channel to the watchlist.
3. Channels added this way are tagged source="auto_discovery".

Seed terms are loaded from active SeedProfiles and their QueryVariants in the
DB (Requirements 2.6, 2.7, 1.5).  When no active profiles exist the engine
falls back to DEFAULT_SEEDS so the system still functions without DB data.

Manual-only mode: set DISCOVERY_ENABLED=false in .env to disable auto-add
but still allow on-demand discovery via the /discovery/search endpoint.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Union

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, Chat

from app.classifiers.classifier import classify
from app.core.config import settings
from app.db.crud import (
    get_active_channels,
    get_variants_for_seed,
    list_seed_profiles,
    record_variant_execution,
    upsert_channel,
)
from app.db.database import get_session

logger = logging.getLogger(__name__)

from app.services.seed_defaults import DEFAULT_SEED_CATALOGUE

DEFAULT_SEEDS: List[str] = [entry["seed_text"] for entry in DEFAULT_SEED_CATALOGUE]


class ChannelDiscoveryEngine:
    def __init__(self, client: TelegramClient) -> None:
        self.client = client
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        # Stagger first run to let the collector authenticate first
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._discovery_cycle()
            except Exception as exc:
                logger.error("Discovery cycle error: %s", exc, exc_info=True)
            await asyncio.sleep(settings.DISCOVERY_INTERVAL_SECONDS)

    async def _discovery_cycle(self) -> None:
        seeds = await self._get_seeds()
        logger.info("Discovery cycle: %d seed terms", len(seeds))
        async with get_session() as db:
            existing = {ch.username.lower() for ch in await get_active_channels(db)}

        for seed in seeds:
            # seed is either a plain string (fallback) or a dict with variant metadata
            seed_text: str = seed["text"] if isinstance(seed, dict) else seed
            try:
                await self._search_and_evaluate(seed, existing)
            except FloodWaitError as fwe:
                logger.warning("FloodWait during discovery — sleeping %ds", fwe.seconds)
                await asyncio.sleep(fwe.seconds + 5)
            except Exception as exc:
                logger.debug("Discovery error for '%s': %s", seed_text, exc)
            await asyncio.sleep(2)  # polite rate-limit between searches

    async def _get_seeds(self) -> List[Union[Dict, str]]:
        """
        Return seed terms from active SeedProfiles + QueryVariants in the DB.

        Each item in the returned list is a dict::

            {
                "text": str,           # variant text to search
                "variant_id": int,     # QueryVariant.id
                "seed_profile_id": int # SeedProfile.id
            }

        Falls back to DEFAULT_SEEDS (plain strings) when no active profiles
        exist so the discovery engine remains functional out of the box.
        """
        try:
            async with get_session() as db:
                profiles = await list_seed_profiles(
                    db,
                    is_active=True,
                    profile=settings.DISCOVERY_PROFILE,
                    status="active",
                )
                search_terms: List[Dict] = []
                for profile in profiles:
                    variants = await get_variants_for_seed(db, profile.id)
                    for variant in variants:
                        search_terms.append({
                            "text": variant.variant_text,
                            "variant_id": variant.id,
                            "seed_profile_id": profile.id,
                        })
                if search_terms:
                    return search_terms
        except Exception as exc:
            logger.debug("Could not load seeds from DB: %s", exc)
        # Fallback: wrap DEFAULT_SEEDS as plain strings
        return DEFAULT_SEEDS  # type: ignore[return-value]

    async def _search_and_evaluate(
        self,
        seed: Union[Dict, str],
        existing: set,
    ) -> None:
        # Unpack whether we have a variant dict or a plain fallback string
        if isinstance(seed, dict):
            seed_text: str = seed["text"]
            variant_id: Optional[int] = seed.get("variant_id")
        else:
            seed_text = seed
            variant_id = None

        result = await self.client(
            SearchRequest(
                q=seed_text,
                limit=settings.DISCOVERY_MAX_RESULTS_PER_QUERY,
            )
        )
        chats = getattr(result, "chats", [])

        found_usernames: List[str] = []
        added_usernames: List[str] = []

        for chat in chats:
            if not isinstance(chat, (Channel, Chat)):
                continue
            username = getattr(chat, "username", None)
            if not username:
                continue
            if username.lower() in existing:
                continue
            # Skip private / broadcast-only channels with no username
            if not getattr(chat, "megagroup", False) and not getattr(chat, "broadcast", False):
                continue

            found_usernames.append(username)

            score = await self._score_channel(username)
            logger.info(
                "Discovered @%s — avg score %.2f (seed: %s)", username, score, seed_text
            )

            if score >= settings.DISCOVERY_MIN_SCORE_TO_ADD:
                try:
                    async with get_session() as db:
                        channel_row = await upsert_channel(
                            db,
                            username=username,
                            telegram_id=chat.id,
                            title=getattr(chat, "title", None),
                        )
                        # Tag the channel with the variant that found it (Req 2.6)
                        if variant_id is not None and channel_row.discovery_variant_id is None:
                            channel_row.discovery_variant_id = variant_id
                except Exception as exc:
                    logger.debug("DB upsert error for @%s: %s", username, exc)

                existing.add(username.lower())
                added_usernames.append(username)
                logger.info(
                    "AUTO-ADDED channel @%s (score %.2f, seed '%s')",
                    username, score, seed_text,
                )

        # Record variant execution metrics (Req 2.7)
        if variant_id is not None:
            try:
                async with get_session() as db:
                    await record_variant_execution(
                        db,
                        query_variant_id=variant_id,
                        scan_job_id=None,
                        channels_found=len(found_usernames),
                        channels_added=len(added_usernames),
                    )
            except Exception as exc:
                logger.debug(
                    "Could not record variant execution for variant_id=%s: %s",
                    variant_id, exc,
                )

    async def _score_channel(self, username: str) -> float:
        """Fetch recent messages and return mean score, excluding petty-only channels."""
        try:
            from app.classifiers.classifier import PETTY_CATEGORIES
            scores: List[float] = []
            all_categories: set = set()
            async for msg in self.client.iter_messages(
                username,
                limit=settings.DISCOVERY_MIN_MESSAGES_TO_SCORE,
            ):
                if msg.message:
                    r = classify(msg.message)
                    scores.append(r.score)
                    all_categories.update(r.categories)
            if not scores:
                return 0.0
            avg = sum(scores) / len(scores)
            # Suppress petty-only channels (colour-trading, betting, task-scam)
            # from auto-add even if they hit the score threshold.
            if all_categories and all(c in PETTY_CATEGORIES for c in all_categories):
                logger.debug(
                    "Petty-only channel @%s suppressed (avg=%.2f cats=%s)",
                    username, avg, all_categories,
                )
                return 0.0  # treat as not qualifying
            return avg
        except Exception as exc:
            logger.debug("Score channel @%s failed: %s", username, exc)
            return 0.0

    async def search_now(self, query: str) -> List[dict]:
        """On-demand search — returns channel info without auto-adding."""
        result = await self.client(
            SearchRequest(q=query, limit=20)
        )
        chats = getattr(result, "chats", [])
        out = []
        for chat in chats:
            if not isinstance(chat, (Channel, Chat)):
                continue
            username = getattr(chat, "username", None)
            if not username:
                continue
            score = await self._score_channel(username)
            out.append({
                "username": username,
                "title": getattr(chat, "title", None),
                "telegram_id": chat.id,
                "members": getattr(chat, "participants_count", None),
                "avg_score": round(score, 3),
                "auto_add_threshold": settings.DISCOVERY_MIN_SCORE_TO_ADD,
                "would_auto_add": score >= settings.DISCOVERY_MIN_SCORE_TO_ADD,
            })
        return sorted(out, key=lambda x: x["avg_score"], reverse=True)


_engine: Optional[ChannelDiscoveryEngine] = None


def get_discovery_engine() -> ChannelDiscoveryEngine:
    global _engine
    if _engine is None:
        from app.collectors.telegram_collector import get_collector
        _engine = ChannelDiscoveryEngine(get_collector().client)
    return _engine