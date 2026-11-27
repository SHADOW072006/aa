import asyncio
import json
import logging
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Set

from telethon.errors import ChannelPrivateError, FloodWaitError, UsernameInvalidError, UsernameNotOccupiedError
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, Chat

from app.classifiers.classifier import classify
from app.core.config import settings
from app.db.crud import (
    list_seed_profiles,
    get_variants_for_seed,
    record_variant_execution,
    upsert_channel,
    upsert_evidence_message,
    insert_evidence_observation,
)
from app.db.database import get_session
from app.db.models import ChannelScanResult, ScanJob
from app.extractors.identifier_extractor import extract
from app.services.pivot_service import extract_pivot_candidates, save_pivot_candidates
from app.services.scoring_service import compute_composite_score, save_channel_score

logger = logging.getLogger(__name__)

from app.services.seed_defaults import DEFAULT_SEED_CATALOGUE

SCAN_MESSAGES_PER_CHANNEL = 100
SCAN_MAX_CHANNELS_PER_SEED = 15
SCAN_RATE_LIMIT_SECONDS = 1.5
TELEGRAM_CONNECT_TIMEOUT_SECONDS = 20
TELEGRAM_SEARCH_TIMEOUT_SECONDS = 30

DEFAULT_SEEDS: List[str] = [entry["seed_text"] for entry in DEFAULT_SEED_CATALOGUE]

# Active background tasks keyed by job_id so we can track them
_active_tasks: Dict[int, asyncio.Task] = {}


async def trigger_scan(
    seed_terms: Optional[List[str]] = None,
    mode: str = None,
    profile: str = "illegal_trade",
) -> int:
    """Create a ScanJob and start it in a background task. Returns job_id."""
    effective_mode = mode or settings.SCAN_DEFAULT_MODE
    is_custom = bool(seed_terms)
    if is_custom:
        seeds = list(seed_terms)  # type: ignore[arg-type]
    else:
        async with get_session() as db:
            db_profiles = list(
                await list_seed_profiles(db, is_active=True, profile=profile, status="active")
            )
        seeds = [p.seed_text for p in db_profiles] if db_profiles else list(DEFAULT_SEEDS)

    async with get_session() as db:
        job = ScanJob(
            seed_terms=json.dumps(seeds),
            status="pending",
        )
        db.add(job)
        await db.flush()
        job_id = job.id

    task = asyncio.create_task(
        _run_scan_job(job_id, seeds, mode=effective_mode, profile=profile, is_custom=is_custom)
    )
    _active_tasks[job_id] = task
    task.add_done_callback(lambda t: _active_tasks.pop(job_id, None))
    logger.info("ScanJob %d started with %d seeds (profile=%s, custom=%s)", job_id, len(seeds), profile, is_custom)
    return job_id


async def _run_scan_job(
    job_id: int,
    seeds: List[str],
    mode: str = "review",
    profile: str = "illegal_trade",
    is_custom: bool = False,
) -> None:
    """Main scan coroutine — runs in background."""
    async with get_session() as db:
        result = await db.execute(
            __import__("sqlalchemy").select(ScanJob).where(ScanJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            return
        job.status = "running"
        job.started_at = datetime.utcnow()

    try:
        from app.collectors.telegram_collector import get_collector
        collector = get_collector()
        client = collector.client

        # A background job must not sit at zero progress when the backend was
        # restarted or its Telegram session is disconnected.  Connect using the
        # stored session only: never prompt for an OTP from a scan request.
        if not client.is_connected():
            await asyncio.wait_for(client.connect(), timeout=TELEGRAM_CONNECT_TIMEOUT_SECONDS)
        authorised = await asyncio.wait_for(
            client.is_user_authorized(), timeout=TELEGRAM_CONNECT_TIMEOUT_SECONDS
        )
        if not authorised:
            raise RuntimeError(
                "Telegram session is not authorised. Reconnect the collector from the backend terminal before starting a scan."
            )

        seen_usernames: Set[str] = set()

        # ------------------------------------------------------------------
        # Phase 1: seed-profile-aware variant scan (ONLY for non-custom profile scans)
        # ------------------------------------------------------------------
        active_profiles = []
        if not is_custom:
            async with get_session() as db:
                active_profiles = list(
                    await list_seed_profiles(db, is_active=True, profile=profile, status="active")
                )

        covered_seeds = {p.seed_text for p in active_profiles}
        for sp in active_profiles:
            async with get_session() as db:
                variants = list(await get_variants_for_seed(db, sp.id))

            # Profile scans use one canonical query per seed.  Running every
            # spacing/transliteration variant turns 62 seeds into hundreds of
            # Telegram searches, leading to rate limits and multi-hour jobs.
            canonical = [variant for variant in variants if variant.is_canonical]
            variants = canonical[:1] or variants[:1]

            for variant in variants:
                variant_id = variant.id
                variant_text = variant.variant_text
                seed_term = sp.seed_text

                channels_found_count = 0
                channels_added_count = 0

                try:
                    found = await _search_channels(client, variant_text)
                    channels_found_count = len(
                        [c for c in found
                         if getattr(c, "username", None)
                         and getattr(c, "username").lower() not in seen_usernames]
                    )

                    async with get_session() as db:
                        result = await db.execute(
                            __import__("sqlalchemy").select(ScanJob).where(ScanJob.id == job_id)
                        )
                        job = result.scalar_one_or_none()
                        if job:
                            job.total_channels_found += channels_found_count

                    for chat in found:
                        username = getattr(chat, "username", None)
                        if not username or username.lower() in seen_usernames:
                            continue
                        seen_usernames.add(username.lower())
                        was_added = await _scan_one_channel(
                            client, chat, seed_term, job_id,
                            seed_term=seed_term,
                            query_variant_id=variant_id,
                            mode=mode,
                        )
                        if was_added:
                            channels_added_count += 1
                        await asyncio.sleep(SCAN_RATE_LIMIT_SECONDS)

                except FloodWaitError as fwe:
                    logger.warning(
                        "FloodWait during variant scan variant=%r — sleeping %ds",
                        variant_text, fwe.seconds,
                    )
                    await asyncio.sleep(fwe.seconds + 5)
                except Exception as exc:
                    logger.error("Variant scan error for %r: %s", variant_text, exc)

                # Record the execution for this variant regardless of errors
                try:
                    async with get_session() as db:
                        await record_variant_execution(
                            db,
                            query_variant_id=variant_id,
                            scan_job_id=job_id,
                            channels_found=channels_found_count,
                            channels_added=channels_added_count,
                        )
                except Exception as exc:
                    logger.warning("Failed to record variant execution for variant_id=%d: %s", variant_id, exc)

        # ------------------------------------------------------------------
        # Phase 2: fallback / custom seed scan
        # ------------------------------------------------------------------
        fallback_seeds = seeds if is_custom else [s for s in seeds if s not in covered_seeds]
        for seed in fallback_seeds:
            try:
                found = await _search_channels(client, seed)
                async with get_session() as db:
                    result = await db.execute(
                        __import__("sqlalchemy").select(ScanJob).where(ScanJob.id == job_id)
                    )
                    job = result.scalar_one_or_none()
                    if job:
                        job.total_channels_found += len(
                            [c for c in found if getattr(c, "username", None)
                             and getattr(c, "username").lower() not in seen_usernames]
                        )

                for chat in found:
                    username = getattr(chat, "username", None)
                    if not username or username.lower() in seen_usernames:
                        continue
                    seen_usernames.add(username.lower())
                    await _scan_one_channel(
                        client, chat, seed, job_id,
                        seed_term=seed,
                        query_variant_id=None,
                        mode=mode,
                    )
                    await asyncio.sleep(SCAN_RATE_LIMIT_SECONDS)

            except FloodWaitError as fwe:
                logger.warning("FloodWait during scan seed=%s — sleeping %ds", seed, fwe.seconds)
                await asyncio.sleep(fwe.seconds + 5)
            except Exception as exc:
                logger.error("Seed scan error for %r: %s", seed, exc)

        async with get_session() as db:
            result = await db.execute(
                __import__("sqlalchemy").select(ScanJob).where(ScanJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if job:
                job.status = "done"
                job.finished_at = datetime.utcnow()

        logger.info("ScanJob %d finished. Scanned=%d Flagged=%d",
                    job_id,
                    (await _get_job_field(job_id, "total_channels_scanned")),
                    (await _get_job_field(job_id, "total_flagged")))

    except Exception as exc:
        logger.error("ScanJob %d failed: %s", job_id, exc, exc_info=True)
        async with get_session() as db:
            result = await db.execute(
                __import__("sqlalchemy").select(ScanJob).where(ScanJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if job:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = datetime.utcnow()


async def _get_job_field(job_id: int, field: str) -> int:
    async with get_session() as db:
        from sqlalchemy import select
        result = await db.execute(select(ScanJob).where(ScanJob.id == job_id))
        job = result.scalar_one_or_none()
        return getattr(job, field, 0) if job else 0


async def _search_channels(client, seed: str) -> List:
    result = await asyncio.wait_for(
        client(SearchRequest(q=seed, limit=SCAN_MAX_CHANNELS_PER_SEED)),
        timeout=TELEGRAM_SEARCH_TIMEOUT_SECONDS,
    )
    chats = getattr(result, "chats", [])
    return [c for c in chats if isinstance(c, (Channel, Chat)) and getattr(c, "username", None)]


async def _scan_one_channel(
    client,
    chat,
    seed: str,
    job_id: int,
    *,
    seed_term: Optional[str] = None,
    query_variant_id: Optional[int] = None,
    mode: str = "review",
) -> bool:
    """
    Scan a single channel.

    Returns True if the channel was newly added to the watchlist, False
    otherwise.  This allows callers to track channels_added_count.
    """
    username = chat.username
    title = getattr(chat, "title", None)
    tg_id = getattr(chat, "id", None)
    member_count = getattr(chat, "participants_count", None)
    is_verified = bool(getattr(chat, "verified", False))
    is_scam = bool(getattr(chat, "scam", False))
    invite_link = f"https://t.me/{username}" if username else None
    channel_desc = getattr(chat, "about", None)

    # Normalise seed_term fallback
    effective_seed_term = seed_term if seed_term is not None else seed

    # Check if already in watchlist
    from sqlalchemy import select
    async with get_session() as db:
        from app.db.models import Channel as DBChannel
        existing_ch = (await db.execute(
            select(DBChannel).where(DBChannel.username == username)
        )).scalar_one_or_none()
    already_monitored = existing_ch is not None and existing_ch.is_active

    scores: List[float] = []
    high_count = 0
    medium_count = 0
    category_counter: Counter = Counter()
    identifier_counter: Counter = Counter()
    sample_msgs: List[dict] = []

    # Per-message evidence tracking
    evidence_rows: List[dict] = []  # for composite scoring later

    # Connecting nodes discovery
    connected_channels: Set[str] = set()
    connected_handles: Set[str] = set()
    connected_phones: Set[str] = set()
    connected_upis: Set[str] = set()
    connected_wallets: Set[str] = set()
    connected_urls: Set[str] = set()

    # We need a scan_result_id before we can link evidence rows, so we
    # collect evidence data during the message loop and persist it after
    # scan_result is flushed.
    pending_evidence: List[dict] = []

    try:
        async for msg in client.iter_messages(username, limit=SCAN_MESSAGES_PER_CHANNEL):
            text = getattr(msg, "message", None) or ""
            if not text.strip():
                continue

            r = classify(text)
            scores.append(r.score)

            if r.risk_level == "HIGH":
                high_count += 1
            elif r.risk_level == "MEDIUM":
                medium_count += 1

            for cat in r.categories:
                category_counter[cat] += 1

            extracted_idents = extract(text)
            for ident in extracted_idents:
                identifier_counter[(ident.type, ident.normalised)] += 1
                if ident.type == "phone":
                    connected_phones.add(ident.normalised)
                elif ident.type == "upi":
                    connected_upis.add(ident.normalised)
                elif ident.type in ("wallet_btc", "wallet_eth", "wallet_usdt"):
                    connected_wallets.add(f"{ident.type}:{ident.normalised}")
                elif ident.type == "handle":
                    norm_h = ident.normalised.lstrip("@")
                    if norm_h.lower() != (username or "").lower():
                        connected_handles.add(norm_h)
                elif ident.type == "url":
                    # Check if it's a telegram channel link
                    tme_match = __import__("re").search(r"t\.me/([a-zA-Z0-9_+]{4,32})", ident.value, __import__("re").IGNORECASE)
                    if tme_match:
                        tme_ch = tme_match.group(1)
                        if tme_ch.lower() != (username or "").lower() and not tme_ch.startswith("joinchat"):
                            connected_channels.add(tme_ch)
                    else:
                        connected_urls.add(ident.value[:60])

            # Forward source
            fwd_source = None
            if hasattr(msg, "fwd_from") and msg.fwd_from:
                if getattr(msg.fwd_from, "from_name", None):
                    fwd_source = msg.fwd_from.from_name
                    connected_channels.add(fwd_source)
                elif getattr(msg.fwd_from, "channel_id", None):
                    fwd_source = f"channel_{msg.fwd_from.channel_id}"

            if r.is_flagged:
                msg_date = getattr(msg, "date", None)
                matched_terms = [t["term"] for t in r.evidence.get("matched_terms", [])] if r.evidence else []
                sender_user = getattr(msg.sender, "username", None) if hasattr(msg, "sender") and msg.sender else None
                sample_msgs.append({
                    "id": getattr(msg, "id", None),
                    "date": msg_date.isoformat() if msg_date else None,
                    "text": text[:800],
                    "score": round(r.score, 3),
                    "categories": r.categories,
                    "risk_level": r.risk_level,
                    "matched_terms": matched_terms,
                    "views": getattr(msg, "views", None),
                    "forwards": getattr(msg, "forwards", None),
                    "fwd_source": fwd_source,
                    "sender_username": sender_user,
                })

            # Collect evidence for messages above threshold (Requirements: 3.1)
            if r.score >= 0.3:
                message_id = getattr(msg, "id", None)
                pending_evidence.append({
                    "telegram_message_id": message_id,
                    "raw_text": text,
                    "normalised_text": r.normalised_text,
                    "classifier_score": r.score,
                    "risk_level": r.risk_level,
                    "severity_tier": r.severity_tier,
                    "categories": json.dumps(r.categories),
                    "matched_terms": json.dumps(r.matched_terms),
                    "seed_term": effective_seed_term,
                    "query_variant_id": query_variant_id,
                })

    except (ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError) as exc:
        logger.debug("Cannot scan @%s: %s", username, exc)
        return False
    except FloodWaitError:
        raise
    except Exception as exc:
        logger.warning("Error scanning @%s: %s", username, exc)

    messages_scanned = len(scores)
    flagged_count = high_count + medium_count
    avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0

    # Determine channel-level risk and severity tier
    from app.classifiers.classifier import CRITICAL_CATEGORIES, HIGH_CATEGORIES, PETTY_CATEGORIES

    top_categories = [cat for cat, _ in category_counter.most_common(8)]
    is_channel_serious = any(c in CRITICAL_CATEGORIES or c in HIGH_CATEGORIES for c in top_categories)

    # Both category tier AND score must justify the level.
    # Prevents HIGH labels on channels with weak average scores.
    _high_min = settings.SCAN_HIGH_RISK_MIN_SCORE
    _med_min = settings.SCAN_MEDIUM_RISK_MIN_SCORE
    _only_petty = (
        bool(top_categories)
        and all(c in PETTY_CATEGORIES for c in top_categories)
    )

    if any(c in CRITICAL_CATEGORIES for c in top_categories) and avg_score >= _med_min:
        channel_severity = "CRITICAL"
        channel_risk = "HIGH"
    elif any(c in HIGH_CATEGORIES for c in top_categories):
        channel_severity = "HIGH"
        if avg_score >= _high_min and high_count >= 2:
            channel_risk = "HIGH"
        elif avg_score >= _med_min and (high_count >= 1 or medium_count >= 3):
            channel_risk = "MEDIUM"
        else:
            channel_risk = "LOW"
    elif _only_petty:
        channel_severity = "PETTY"
        channel_risk = "LOW"
    elif avg_score >= _high_min and high_count >= 2:
        channel_severity = "MEDIUM"
        channel_risk = "HIGH"
    elif avg_score >= _med_min and (high_count >= 1 or medium_count >= 3):
        channel_severity = "MEDIUM"
        channel_risk = "MEDIUM"
    else:
        channel_severity = "LOW"
        channel_risk = "LOW"

    top_identifiers = [
        {"type": t, "value": v}
        for (t, v), _ in identifier_counter.most_common(15)
    ]
    # Keep top 12 sample messages by score
    sample_msgs.sort(key=lambda x: x["score"], reverse=True)
    sample_msgs = sample_msgs[:12]

    connected_nodes_dict = {
        "channels": sorted(list(connected_channels))[:20],
        "handles": sorted(list(connected_handles))[:20],
        "phones": sorted(list(connected_phones))[:20],
        "upis": sorted(list(connected_upis))[:20],
        "wallets": sorted(list(connected_wallets))[:20],
        "urls": sorted(list(connected_urls))[:20],
    }

    channel_added_to_watchlist = False

    async with get_session() as db:
        scan_result = ChannelScanResult(
            scan_job_id=job_id,
            channel_username=username,
            channel_title=title,
            channel_description=channel_desc,
            telegram_id=tg_id,
            member_count=member_count,
            is_verified=is_verified,
            is_scam=is_scam,
            invite_link=invite_link,
            messages_scanned=messages_scanned,
            flagged_count=flagged_count,
            high_count=high_count,
            medium_count=medium_count,
            avg_score=avg_score,
            top_categories=json.dumps(top_categories),
            top_identifiers=json.dumps(top_identifiers),
            sample_messages=json.dumps(sample_msgs),
            connected_nodes=json.dumps(connected_nodes_dict),
            risk_level=channel_risk,
            severity_tier=channel_severity,
            is_serious=is_channel_serious,
            seed_term=seed,
            already_monitored=already_monitored,
        )
        db.add(scan_result)
        await db.flush()

        channel_scan_result_id = scan_result.id

        # Auto-add: only in auto mode with sufficient evidence.
        # In review mode the analyst decides from the scan results page.
        _serious_enough = (
            channel_risk in ("HIGH", "MEDIUM")
            and high_count >= settings.SCAN_AUTO_ADD_MIN_HIGH_MSGS
            and channel_severity not in ("PETTY",)
        )
        if mode == "auto" and _serious_enough and not already_monitored:
            await upsert_channel(db, username=username, telegram_id=tg_id, title=title)
            channel_added_to_watchlist = True
            logger.info(
                "AUTO-ADDED @%s (risk=%s, high_msgs=%d, severity=%s)",
                username, channel_risk, high_count, channel_severity,
            )
        elif channel_risk in ("HIGH", "MEDIUM") and not already_monitored:
            logger.info(
                "REVIEW-PENDING @%s (risk=%s, high_msgs=%d, severity=%s, mode=%s)",
                username, channel_risk, high_count, channel_severity, mode,
            )

        # Update job counters
        from sqlalchemy import select, update
        await db.execute(
            update(ScanJob)
            .where(ScanJob.id == job_id)
            .values(
                total_channels_scanned=ScanJob.total_channels_scanned + 1,
                total_messages_scanned=ScanJob.total_messages_scanned + messages_scanned,
                total_flagged=ScanJob.total_flagged + flagged_count,
            )
        )

        # ------------------------------------------------------------------
        # Requirement 3.1 — persist per-message evidence
        # Requirement 3.2 — extract and save pivot candidates per message
        # ------------------------------------------------------------------
        saved_evidence_list: List[dict] = []

        for ev in pending_evidence:
            message_id = ev["telegram_message_id"]
            normalised_text = ev["normalised_text"] or ""

            try:
                ev_msg = await upsert_evidence_message(
                    db,
                    channel_username=username,
                    telegram_message_id=message_id,
                    raw_text=ev["raw_text"],
                    normalised_text=ev["normalised_text"],
                    message_timestamp=ev.get("message_timestamp"),
                    ocr_outcome="not_applicable",
                )
                obs = await insert_evidence_observation(
                    db,
                    evidence_message_id=ev_msg.id,
                    source_type="scheduled_scan",
                    score=ev["classifier_score"],
                    risk_level=ev["risk_level"],
                    severity_tier=ev["severity_tier"],
                    scan_job_id=job_id,
                    channel_scan_result_id=channel_scan_result_id,
                    query_variant_id=ev["query_variant_id"],
                    categories=ev["categories"],
                    matched_terms=ev["matched_terms"],
                )
                # Accumulate evidence data for composite scoring
                saved_evidence_list.append({
                    "classifier_score": ev["classifier_score"],
                    "risk_level": ev["risk_level"],
                    "severity_tier": ev["severity_tier"],
                })
            except Exception as exc:
                logger.warning(
                    "Failed to save evidence_v2 for @%s msg_id=%s: %s",
                    username, message_id, exc,
                )
                continue

            # Pivot candidate extraction (Requirement 3.2, 4.1)
            try:
                pivot_candidates = extract_pivot_candidates(normalised_text, username)
                if pivot_candidates:
                    await save_pivot_candidates(
                        db,
                        candidates=pivot_candidates,
                        source_channel_username=username,
                        source_scan_result_id=channel_scan_result_id,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to save pivot candidates for @%s msg_id=%s: %s",
                    username, message_id, exc,
                )

        # ------------------------------------------------------------------
        # Requirement 5.1 — composite scoring at end of channel scan
        # ------------------------------------------------------------------
        try:
            # Count approved pivots for this channel's scan result
            from app.db.models import PivotCandidate
            from sqlalchemy import select as sa_select
            approved_pivot_result = await db.execute(
                sa_select(PivotCandidate).where(
                    PivotCandidate.source_scan_result_id == channel_scan_result_id,
                    PivotCandidate.status == "approved",
                )
            )
            approved_pivots = approved_pivot_result.scalars().all()

            score_dict = compute_composite_score(
                saved_evidence_list,
                valid_pivot_count=len(approved_pivots),
            )
            await save_channel_score(
                db,
                channel_scan_result_id=channel_scan_result_id,
                score_dict=score_dict,
            )
        except Exception as exc:
            logger.warning(
                "Failed to compute/save composite score for @%s (result_id=%s): %s",
                username, channel_scan_result_id, exc,
            )

    logger.info(
        "Scanned @%s: %d msgs, %d flagged, risk=%s, seed=%r",
        username, messages_scanned, flagged_count, channel_risk, seed,
    )

    return channel_added_to_watchlist
