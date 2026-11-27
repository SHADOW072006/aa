"""
CRUD helpers – thin wrappers around SQLAlchemy async operations.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Alert, Channel, EntityLink, Identifier, Message


# ── Channels ──────────────────────────────────────────────────────────────────

async def get_channel_by_username(db: AsyncSession, username: str) -> Optional[Channel]:
    # Exact match first; usernames are case-insensitive on Telegram, so fall
    # back to a case-insensitive lookup instead of creating a duplicate channel.
    result = await db.execute(select(Channel).where(Channel.username == username))
    channel = result.scalar_one_or_none()
    if channel is None:
        result = await db.execute(
            select(Channel)
            .where(func.lower(Channel.username) == username.strip().lower())
            .order_by(Channel.id)
        )
        channel = result.scalars().first()
    return channel


async def get_active_channels(db: AsyncSession) -> Sequence[Channel]:
    result = await db.execute(select(Channel).where(Channel.is_active == True))
    return result.scalars().all()


async def get_due_channels(
    db: AsyncSession,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> Sequence[Channel]:
    """
    Return active channels whose next_poll_at is in the past (or NULL).

    Channels are ordered by priority:
      1. poll_tier: HIGH=0, MEDIUM=1, LOW/NULL=2
      2. next_poll_at ASC (NULL first — treat as immediately due)

    Only returns channels with channel_status IN ('active', None).
    Does not return channels with status 'inaccessible', 'paused', or
    'error_state'.

    Parameters
    ----------
    db : AsyncSession
    now : datetime | None
        Reference timestamp. Defaults to datetime.utcnow() if not provided.
    limit : int
        Maximum number of channels to return per tick (default 50).
    """
    from sqlalchemy import case, or_, asc, nullsfirst
    if now is None:
        now = datetime.utcnow()

    # Priority: HIGH=0, MEDIUM=1, LOW or NULL=2
    tier_priority = case(
        (Channel.poll_tier == "HIGH", 0),
        (Channel.poll_tier == "MEDIUM", 1),
        else_=2,
    )

    result = await db.execute(
        select(Channel)
        .where(
            Channel.is_active == True,
            or_(
                Channel.channel_status == "active",
                Channel.channel_status == None,
            ),
            or_(
                Channel.next_poll_at == None,
                Channel.next_poll_at <= now,
            ),
        )
        .order_by(tier_priority, nullsfirst(asc(Channel.next_poll_at)))
        .limit(limit)
    )
    return result.scalars().all()


async def update_channel_next_poll(
    db: AsyncSession,
    channel_id: int,
    next_poll_at: datetime,
    channel_status: Optional[str] = None,
    consecutive_error_count: Optional[int] = None,
    error_state: Optional[bool] = None,
) -> None:
    """Update next_poll_at and optional status/error fields on a channel."""
    values: dict = {"next_poll_at": next_poll_at}
    if channel_status is not None:
        values["channel_status"] = channel_status
    if consecutive_error_count is not None:
        values["consecutive_error_count"] = consecutive_error_count
    if error_state is not None:
        values["error_state"] = error_state
    await db.execute(
        update(Channel).where(Channel.id == channel_id).values(**values)
    )


async def upsert_channel(
    db: AsyncSession,
    username: str,
    telegram_id: Optional[int] = None,
    title: Optional[str] = None,
) -> Channel:
    channel = await get_channel_by_username(db, username)
    if channel is None:
        channel = Channel(username=username, telegram_id=telegram_id, title=title)
        db.add(channel)
        await db.flush()
    else:
        if telegram_id:
            channel.telegram_id = telegram_id
        if title:
            channel.title = title
    return channel


async def mark_channel_fetched(db: AsyncSession, channel_id: int, last_msg_id: int) -> None:
    await db.execute(
        update(Channel)
        .where(Channel.id == channel_id)
        .values(last_fetched_at=datetime.utcnow(), last_message_id=last_msg_id)
    )


# ── Messages ──────────────────────────────────────────────────────────────────

async def get_message_by_channel_and_id(
    db: AsyncSession, channel_id: int, telegram_msg_id: int
) -> Optional[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.channel_id == channel_id, Message.telegram_msg_id == telegram_msg_id)
        .order_by(Message.id.desc())
    )
    # Older imports may predate the database uniqueness constraint.  Treat a
    # duplicate as an already-collected message instead of aborting the poll.
    return result.scalars().first()


async def save_message(db: AsyncSession, message: Message) -> Message:
    db.add(message)
    await db.flush()
    return message


async def get_messages_paginated(
    db: AsyncSession,
    channel_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[Message]:
    q = select(Message).options(selectinload(Message.channel))
    if channel_id:
        q = q.where(Message.channel_id == channel_id)
    q = q.order_by(Message.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


# ── Alerts ────────────────────────────────────────────────────────────────────

async def save_alert(db: AsyncSession, alert: Alert) -> Alert:
    db.add(alert)
    await db.flush()
    return alert


async def get_alerts_paginated(
    db: AsyncSession,
    risk_level: Optional[str] = None,
    reviewed: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
    include_low: bool = False,
    lifecycle_state: Optional[str] = None,
    include_historical: bool = False,
) -> Sequence[Alert]:
    q = (
        select(Alert)
        .options(
            selectinload(Alert.message).selectinload(Message.channel),
            selectinload(Alert.message).selectinload(Message.identifiers),
        )
        .order_by(Alert.created_at.desc())
    )
    if lifecycle_state:
        q = q.where(Alert.lifecycle_state == lifecycle_state)
    elif not include_historical:
        q = q.where(Alert.lifecycle_state == "active")

    if risk_level:
        q = q.where(Alert.risk_level == risk_level.upper())
    elif not include_low and not include_historical and not lifecycle_state:
        q = q.where(Alert.risk_level.in_(("HIGH", "MEDIUM")))

    if reviewed is not None:
        q = q.where(Alert.is_reviewed == reviewed)
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


async def get_alert_counts(db: AsyncSession, *, include_historical: bool = False) -> dict:
    q = select(Alert.risk_level, func.count(Alert.id))
    if not include_historical:
        q = q.where(
            Alert.lifecycle_state == "active",
            Alert.risk_level.in_(("HIGH", "MEDIUM")),
        )
    q = q.group_by(Alert.risk_level)
    result = await db.execute(q)
    rows = result.all()
    return {row[0]: row[1] for row in rows}


async def mark_alert_reviewed(db: AsyncSession, alert_id: int, reviewed_by: str) -> None:
    await db.execute(
        update(Alert)
        .where(Alert.id == alert_id)
        .values(is_reviewed=True, reviewed_by=reviewed_by)
    )


# ── Identifiers ───────────────────────────────────────────────────────────────

async def save_identifiers(db: AsyncSession, identifiers: List[Identifier]) -> None:
    for ident in identifiers:
        db.add(ident)
    await db.flush()


async def get_identifiers_by_value(
    db: AsyncSession, normalised: str
) -> Sequence[Identifier]:
    from sqlalchemy import or_

    q = normalised.strip().lstrip("@").lower()
    digits = "".join(ch for ch in q if ch.isdigit())
    conds = [
        Identifier.normalised.ilike(f"%{q}%"),
        Identifier.value.ilike(f"%{q}%"),
    ]
    if len(digits) >= 5:
        conds.append(Identifier.normalised.ilike(f"%{digits}%"))

    result = await db.execute(
        select(Identifier)
        .options(
            selectinload(Identifier.message).selectinload(Message.channel),
            selectinload(Identifier.message).selectinload(Message.alert),
            selectinload(Identifier.message).selectinload(Message.identifiers),
        )
        .where(or_(*conds))
        .order_by(Identifier.created_at.desc())
        .limit(100)
    )
    return result.scalars().all()


async def get_all_identifiers_for_graph(db: AsyncSession) -> Sequence[Identifier]:
    result = await db.execute(
        select(Identifier).order_by(Identifier.message_id)
    )
    return result.scalars().all()


# ── Entity links ──────────────────────────────────────────────────────────────

async def upsert_entity_link(
    db: AsyncSession, source_id: int, target_id: int
) -> None:
    # Canonical ordering avoids duplicate reversed edges
    lo, hi = min(source_id, target_id), max(source_id, target_id)
    result = await db.execute(
        select(EntityLink).where(EntityLink.source_id == lo, EntityLink.target_id == hi)
    )
    link = result.scalar_one_or_none()
    if link is None:
        db.add(EntityLink(source_id=lo, target_id=hi, weight=1.0, last_seen=datetime.utcnow()))
    else:
        link.weight += 1.0
        link.last_seen = datetime.utcnow()
    await db.flush()


async def get_entity_links(db: AsyncSession) -> Sequence[EntityLink]:
    result = await db.execute(select(EntityLink))
    return result.scalars().all()


# =============================================================================
# New CRUD helpers for intelligence-platform models
# Requirements: 1.2, 4.2, 5.4, 6.1, 7.1, 8.3, 9.1
# =============================================================================

from datetime import datetime

from app.db.models import (
    ChannelHealthEvent,
    ChannelScoreComponents,
    DispositionHistory,
    PivotCandidate,
    QueryVariant,
    QueryVariantExecution,
    ScanEvidence,
    SeedProfile,
)
from app.extractors.normaliser import normalise as normalise_seed


# ── SeedProfile ───────────────────────────────────────────────────────────────

async def create_seed_profile(
    db: AsyncSession,
    seed_text: str,
    threat_category: str,
    language_region: str,
    intent_type: str,
    priority: int,
    created_source: str,
    *,
    profile: str = "illegal_trade",
    seed_role: str = "indicator",
    status: str = "active",
    rationale: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> SeedProfile:
    """Create a new SeedProfile, normalising seed_text into seed_text_normalised."""
    effective_active = (status == "active") if is_active is None else is_active
    sp = SeedProfile(
        seed_text=seed_text,
        seed_text_normalised=normalise_seed(seed_text),
        threat_category=threat_category,
        language_region=language_region,
        intent_type=intent_type,
        priority=priority,
        is_active=effective_active,
        profile=profile,
        seed_role=seed_role,
        status=status,
        rationale=rationale,
        created_source=created_source,
    )
    db.add(sp)
    await db.flush()
    return sp


async def get_seed_profile_by_id(
    db: AsyncSession, profile_id: int
) -> Optional[SeedProfile]:
    result = await db.execute(
        select(SeedProfile).where(SeedProfile.id == profile_id)
    )
    return result.scalar_one_or_none()


async def get_seed_profile_by_normalised(
    db: AsyncSession, normalised_text: str
) -> Optional[SeedProfile]:
    result = await db.execute(
        select(SeedProfile).where(
            SeedProfile.seed_text_normalised == normalised_text
        )
    )
    return result.scalar_one_or_none()


async def list_seed_profiles(
    db: AsyncSession,
    is_active: Optional[bool] = None,
    threat_category: Optional[str] = None,
    profile: Optional[str] = None,
    status: Optional[str] = None,
    seed_role: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[SeedProfile]:
    q = select(SeedProfile)
    if is_active is not None:
        q = q.where(SeedProfile.is_active == is_active)
    if threat_category is not None:
        q = q.where(SeedProfile.threat_category == threat_category)
    if profile is not None:
        q = q.where(SeedProfile.profile == profile)
    if status is not None:
        q = q.where(SeedProfile.status == status)
    if seed_role is not None:
        q = q.where(SeedProfile.seed_role == seed_role)
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


async def update_seed_profile(
    db: AsyncSession, profile_id: int, **kwargs
) -> Optional[SeedProfile]:
    """Update arbitrary columns on a SeedProfile by id."""
    profile = await get_seed_profile_by_id(db, profile_id)
    if profile is None:
        return None
    for key, value in kwargs.items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    await db.flush()
    return profile


async def deactivate_seed_profile(db: AsyncSession, profile_id: int) -> bool:
    """Set is_active=False on the given SeedProfile. Returns True if found."""
    profile = await get_seed_profile_by_id(db, profile_id)
    if profile is None:
        return False
    profile.is_active = False
    await db.flush()
    return True


# ── QueryVariant ──────────────────────────────────────────────────────────────

async def create_query_variant(
    db: AsyncSession,
    seed_profile_id: int,
    variant_text: str,
    variant_type: str,
    is_canonical: bool = False,
) -> QueryVariant:
    variant = QueryVariant(
        seed_profile_id=seed_profile_id,
        variant_text=variant_text,
        variant_type=variant_type,
        is_canonical=is_canonical,
    )
    db.add(variant)
    await db.flush()
    return variant


async def get_variants_for_seed(
    db: AsyncSession, seed_profile_id: int
) -> Sequence[QueryVariant]:
    result = await db.execute(
        select(QueryVariant).where(
            QueryVariant.seed_profile_id == seed_profile_id
        )
    )
    return result.scalars().all()


async def get_variant_by_text(
    db: AsyncSession, variant_text: str
) -> Optional[QueryVariant]:
    result = await db.execute(
        select(QueryVariant).where(QueryVariant.variant_text == variant_text)
    )
    return result.scalar_one_or_none()


# ── QueryVariantExecution ─────────────────────────────────────────────────────

async def record_variant_execution(
    db: AsyncSession,
    query_variant_id: int,
    scan_job_id: Optional[int],
    channels_found: int,
    channels_added: int,
) -> QueryVariantExecution:
    execution = QueryVariantExecution(
        query_variant_id=query_variant_id,
        scan_job_id=scan_job_id,
        channels_found=channels_found,
        channels_added=channels_added,
    )
    db.add(execution)
    await db.flush()
    return execution


# ── ScanEvidence ──────────────────────────────────────────────────────────────

async def upsert_scan_evidence(
    db: AsyncSession,
    channel_username: str,
    telegram_message_id: int,
    **kwargs,
) -> ScanEvidence:
    """
    Get-or-create on the (channel_username, telegram_message_id) unique
    constraint.  On create all kwargs are set as initial field values; on
    update only the supplied kwargs are applied.
    """
    result = await db.execute(
        select(ScanEvidence).where(
            ScanEvidence.channel_username == channel_username,
            ScanEvidence.telegram_message_id == telegram_message_id,
        )
    )
    evidence = result.scalar_one_or_none()
    if evidence is None:
        evidence = ScanEvidence(
            channel_username=channel_username,
            telegram_message_id=telegram_message_id,
            **kwargs,
        )
        db.add(evidence)
    else:
        for key, value in kwargs.items():
            if hasattr(evidence, key):
                setattr(evidence, key, value)
    await db.flush()
    return evidence


async def get_evidence_for_scan(
    db: AsyncSession,
    scan_job_id: int,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[ScanEvidence]:
    result = await db.execute(
        select(ScanEvidence)
        .where(ScanEvidence.scan_job_id == scan_job_id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def get_evidence_for_channel(
    db: AsyncSession,
    channel_username: str,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[ScanEvidence]:
    result = await db.execute(
        select(ScanEvidence)
        .where(ScanEvidence.channel_username == channel_username)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def update_evidence_disposition(
    db: AsyncSession,
    evidence_id: int,
    disposition: str,
    disposition_notes: Optional[str],
    disposition_by: str,
) -> Optional[ScanEvidence]:
    result = await db.execute(
        select(ScanEvidence).where(ScanEvidence.id == evidence_id)
    )
    evidence = result.scalar_one_or_none()
    if evidence is None:
        return None
    evidence.disposition = disposition
    evidence.disposition_notes = disposition_notes
    evidence.disposition_by = disposition_by
    evidence.disposition_at = datetime.utcnow()
    await db.flush()
    return evidence


# ── PivotCandidate ────────────────────────────────────────────────────────────

async def upsert_pivot_candidate(
    db: AsyncSession,
    source_channel_username: str,
    candidate_type: str,
    candidate_value: str,
    source_scan_result_id: Optional[int] = None,
) -> PivotCandidate:
    """
    Get-or-create on the (candidate_value, source_channel_username) unique
    constraint.  source_scan_result_id is only applied on initial creation.
    """
    result = await db.execute(
        select(PivotCandidate).where(
            PivotCandidate.candidate_value == candidate_value,
            PivotCandidate.source_channel_username == source_channel_username,
        )
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        candidate = PivotCandidate(
            source_channel_username=source_channel_username,
            candidate_type=candidate_type,
            candidate_value=candidate_value,
            source_scan_result_id=source_scan_result_id,
        )
        db.add(candidate)
        await db.flush()
    return candidate


async def list_pivot_candidates(
    db: AsyncSession,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[PivotCandidate]:
    q = select(PivotCandidate)
    if status is not None:
        q = q.where(PivotCandidate.status == status)
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


async def update_pivot_status(
    db: AsyncSession,
    pivot_id: int,
    status: str,
    evaluated_by: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[PivotCandidate]:
    result = await db.execute(
        select(PivotCandidate).where(PivotCandidate.id == pivot_id)
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        return None
    candidate.status = status
    candidate.evaluated_at = datetime.utcnow()
    if evaluated_by is not None:
        candidate.evaluated_by = evaluated_by
    if notes is not None:
        candidate.notes = notes
    await db.flush()
    return candidate


# ── ChannelScoreComponents ────────────────────────────────────────────────────

async def upsert_channel_score(
    db: AsyncSession,
    channel_scan_result_id: int,
    **score_fields,
) -> ChannelScoreComponents:
    """
    Get-or-create on channel_scan_result_id.  All score_fields are applied on
    both create and update.
    """
    result = await db.execute(
        select(ChannelScoreComponents).where(
            ChannelScoreComponents.channel_scan_result_id == channel_scan_result_id
        )
    )
    score = result.scalar_one_or_none()
    if score is None:
        score = ChannelScoreComponents(
            channel_scan_result_id=channel_scan_result_id,
            **score_fields,
        )
        db.add(score)
    else:
        for key, value in score_fields.items():
            if hasattr(score, key):
                setattr(score, key, value)
    await db.flush()
    return score


async def get_score_for_result(
    db: AsyncSession, channel_scan_result_id: int
) -> Optional[ChannelScoreComponents]:
    result = await db.execute(
        select(ChannelScoreComponents).where(
            ChannelScoreComponents.channel_scan_result_id == channel_scan_result_id
        )
    )
    return result.scalar_one_or_none()


# ── ChannelHealthEvent ────────────────────────────────────────────────────────

async def record_health_event(
    db: AsyncSession,
    channel_id: int,
    event_type: str,
    error_message: Optional[str] = None,
) -> ChannelHealthEvent:
    event = ChannelHealthEvent(
        channel_id=channel_id,
        event_type=event_type,
        error_message=error_message,
    )
    db.add(event)
    await db.flush()
    return event


async def get_health_events(
    db: AsyncSession, channel_id: int, limit: int = 50
) -> Sequence[ChannelHealthEvent]:
    result = await db.execute(
        select(ChannelHealthEvent)
        .where(ChannelHealthEvent.channel_id == channel_id)
        .order_by(ChannelHealthEvent.occurred_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


# ── DispositionHistory ────────────────────────────────────────────────────────

async def record_disposition_change(
    db: AsyncSession,
    target_type: str,
    target_id: int,
    previous_disposition: Optional[str],
    new_disposition: str,
    changed_by: str,
    notes: Optional[str] = None,
) -> DispositionHistory:
    history = DispositionHistory(
        target_type=target_type,
        target_id=target_id,
        previous_disposition=previous_disposition,
        new_disposition=new_disposition,
        changed_by=changed_by,
        notes=notes,
    )
    db.add(history)
    await db.flush()
    return history


async def get_disposition_history(
    db: AsyncSession, target_type: str, target_id: int
) -> Sequence[DispositionHistory]:
    result = await db.execute(
        select(DispositionHistory)
        .where(
            DispositionHistory.target_type == target_type,
            DispositionHistory.target_id == target_id,
        )
        .order_by(DispositionHistory.changed_at.asc())
    )
    return result.scalars().all()


# ── EvidenceMessage & EvidenceObservation ──────────────────────────────────────
# Tasks 6 & 7 — Requirements: 6, 7, 8, 9, 10

async def upsert_evidence_message(
    db: AsyncSession,
    channel_username: str,
    telegram_message_id: int,
    *,
    message_timestamp: Optional[datetime] = None,
    raw_text: Optional[str] = None,
    caption_text: Optional[str] = None,
    ocr_text: Optional[str] = None,
    normalised_text: Optional[str] = None,
    extracted_identifiers: Optional[str] = None,
    media_path: Optional[str] = None,
    media_hash: Optional[str] = None,
    ocr_outcome: Optional[str] = None,
    ocr_skip_reason: Optional[str] = None,
) -> "EvidenceMessage":
    """
    Get-or-create an EvidenceMessage for the given (channel_username, telegram_message_id).

    On CREATE: sets first_seen_at = now(), last_seen_at = now(), copies all provided fields.
    On UPDATE: updates last_seen_at = now() and updates mutable content fields
               (raw_text, ocr_text, normalised_text, etc.) ONLY if the new value is not None
               and the existing value is None (i.e. we fill gaps but do not overwrite content).
               NEVER updates disposition, first_seen_at.
    """
    from app.db.models import EvidenceMessage
    result = await db.execute(
        select(EvidenceMessage).where(
            EvidenceMessage.channel_username == channel_username,
            EvidenceMessage.telegram_message_id == telegram_message_id,
        )
    )
    ev = result.scalar_one_or_none()
    if ev is None:
        ev = EvidenceMessage(
            channel_username=channel_username,
            telegram_message_id=telegram_message_id,
            message_timestamp=message_timestamp,
            raw_text=raw_text,
            caption_text=caption_text,
            ocr_text=ocr_text,
            normalised_text=normalised_text,
            extracted_identifiers=extracted_identifiers,
            media_path=media_path,
            media_hash=media_hash,
            ocr_outcome=ocr_outcome,
            ocr_skip_reason=ocr_skip_reason,
            first_seen_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        db.add(ev)
        await db.flush()
    else:
        ev.last_seen_at = datetime.utcnow()
        # Fill in gaps — do not overwrite existing content
        if raw_text is not None and ev.raw_text is None:
            ev.raw_text = raw_text
        if caption_text is not None and ev.caption_text is None:
            ev.caption_text = caption_text
        if ocr_text is not None and ev.ocr_text is None:
            ev.ocr_text = ocr_text
        if normalised_text is not None and ev.normalised_text is None:
            ev.normalised_text = normalised_text
        if extracted_identifiers is not None and ev.extracted_identifiers is None:
            ev.extracted_identifiers = extracted_identifiers
        if media_path is not None and ev.media_path is None:
            ev.media_path = media_path
        if media_hash is not None and ev.media_hash is None:
            ev.media_hash = media_hash
        if ocr_outcome is not None and ev.ocr_outcome is None:
            ev.ocr_outcome = ocr_outcome
        if ocr_skip_reason is not None and ev.ocr_skip_reason is None:
            ev.ocr_skip_reason = ocr_skip_reason
        if message_timestamp is not None and ev.message_timestamp is None:
            ev.message_timestamp = message_timestamp
    return ev


async def insert_evidence_observation(
    db: AsyncSession,
    evidence_message_id: int,
    *,
    source_type: str,
    score: float,
    risk_level: str,
    severity_tier: str,
    scan_job_id: Optional[int] = None,
    channel_scan_result_id: Optional[int] = None,
    seed_profile_id: Optional[int] = None,
    query_variant_id: Optional[int] = None,
    classifier_version: str = "lexicon_v1",
    categories: Optional[str] = None,
    matched_terms: Optional[str] = None,
) -> "EvidenceObservation":
    """
    Always INSERT a new EvidenceObservation — never update or deduplicate.
    This preserves the full classification history.
    """
    from app.db.models import EvidenceObservation
    obs = EvidenceObservation(
        evidence_message_id=evidence_message_id,
        scan_job_id=scan_job_id,
        channel_scan_result_id=channel_scan_result_id,
        seed_profile_id=seed_profile_id,
        query_variant_id=query_variant_id,
        source_type=source_type,
        classifier_version=classifier_version,
        score=score,
        risk_level=risk_level,
        severity_tier=severity_tier,
        categories=categories,
        matched_terms=matched_terms,
        classified_at=datetime.utcnow(),
    )
    db.add(obs)
    await db.flush()
    return obs


async def get_evidence_message(
    db: AsyncSession, evidence_message_id: int
) -> Optional["EvidenceMessage"]:
    """Return a single EvidenceMessage by primary key."""
    from app.db.models import EvidenceMessage
    result = await db.execute(
        select(EvidenceMessage).where(EvidenceMessage.id == evidence_message_id)
    )
    return result.scalar_one_or_none()


async def get_observations_for_message(
    db: AsyncSession, evidence_message_id: int
) -> Sequence:
    """Return all EvidenceObservation rows for a message, newest first."""
    from app.db.models import EvidenceObservation
    result = await db.execute(
        select(EvidenceObservation)
        .where(EvidenceObservation.evidence_message_id == evidence_message_id)
        .order_by(EvidenceObservation.classified_at.desc())
    )
    return result.scalars().all()


async def list_evidence_messages(
    db: AsyncSession,
    *,
    channel_username: Optional[str] = None,
    disposition: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 100,
) -> Sequence:
    """
    Return a filtered, paginated list of EvidenceMessage rows.

    Filters:
        channel_username  – exact match on channel_username
        disposition       – exact match on disposition (use "none" to filter for NULL)
        date_from         – first_seen_at >= date_from
        date_to           – first_seen_at <= date_to

    Results are ordered by first_seen_at DESC.
    """
    from app.db.models import EvidenceMessage
    q = select(EvidenceMessage)
    if channel_username:
        q = q.where(EvidenceMessage.channel_username == channel_username)
    if disposition is not None:
        if disposition.lower() == "none":
            q = q.where(EvidenceMessage.disposition == None)
        else:
            q = q.where(EvidenceMessage.disposition == disposition)
    if date_from:
        q = q.where(EvidenceMessage.first_seen_at >= date_from)
    if date_to:
        q = q.where(EvidenceMessage.first_seen_at <= date_to)
    q = q.order_by(EvidenceMessage.first_seen_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


async def set_evidence_message_disposition(
    db: AsyncSession,
    evidence_message_id: int,
    disposition: str,
    notes: Optional[str],
    changed_by: str,
) -> Optional["EvidenceMessage"]:
    """
    Set the disposition on an EvidenceMessage and write an audit entry
    to DispositionHistory.

    Returns the updated EvidenceMessage, or None if not found.
    Valid dispositions: confirmed_threat, false_positive, needs_review, escalated.
    """
    from app.db.models import EvidenceMessage, DispositionHistory

    VALID = {"confirmed_threat", "false_positive", "needs_review", "escalated"}
    if disposition not in VALID:
        raise ValueError(f"Invalid disposition '{disposition}'. Must be one of {VALID}")

    result = await db.execute(
        select(EvidenceMessage).where(EvidenceMessage.id == evidence_message_id)
    )
    ev = result.scalar_one_or_none()
    if ev is None:
        return None

    history = DispositionHistory(
        target_type="evidence_message",
        target_id=evidence_message_id,
        previous_disposition=ev.disposition,
        new_disposition=disposition,
        changed_by=changed_by,
        notes=notes,
        changed_at=datetime.utcnow(),
    )
    db.add(history)

    ev.disposition = disposition
    ev.disposition_notes = notes
    ev.disposition_by = changed_by
    ev.disposition_at = datetime.utcnow()
    await db.flush()
    return ev
