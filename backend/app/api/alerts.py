"""
Alert endpoints.

GET  /alerts                   Paginated list (filterable by risk level, reviewed)
GET  /alerts/{id}              Single alert with full evidence
PATCH /alerts/{id}/review      Mark as reviewed
GET  /alerts/stats             Counts by risk level
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.crud import (
    get_alert_counts,
    get_alerts_paginated,
    mark_alert_reviewed,
)
from app.db.database import get_db
from app.db.models import Alert, Channel, EvidenceMessage, EvidenceObservation, Identifier, Message
from app.extractors.identifier_extractor import CONTACT_TYPES, mask_identifier
from app.services.evidence_hashing import provenance_note_for_status
from app.services.minhash_service import get_minhash_index
from app.services.retention_service import is_caller_authorized, require_api_token, write_audit_log

router = APIRouter(prefix="/alerts", tags=["alerts"])


class IdentifierOut(BaseModel):
    type: str
    value: str
    normalised: str

    model_config = {"from_attributes": True}


class MessageSnapshot(BaseModel):
    id: int
    telegram_msg_id: int
    text: Optional[str]
    created_at: str
    channel_username: str
    channel_title: Optional[str]
    sender_username: Optional[str]
    has_media: bool
    media_path: Optional[str]
    identifiers: List[IdentifierOut]


class AlertOut(BaseModel):
    id: int
    risk_level: str
    score: float
    categories: Optional[str]
    evidence: Optional[Any]
    is_reviewed: bool
    reviewed_by: Optional[str]
    created_at: str
    message: MessageSnapshot


def _serialise_alert(
    alert,
    *,
    mask_identifiers: bool = True,
    include_raw_content: bool = False,
    observation_count: int = 1,
    similar_channels_count: int = 0,
    shared_identifier_channels: Optional[List[str]] = None,
) -> Dict:
    msg = alert.message
    ev_dict = json.loads(alert.evidence) if alert.evidence else {}
    scoring_ver = getattr(alert, "latest_scoring_version", None) or ev_dict.get("scoring_version")
    classification_state = "latest" if scoring_ver == settings.SCORING_VERSION else "legacy"
    cats = [c.strip() for c in (alert.categories or "").split(",") if c.strip()]
    leg_cats_raw = getattr(alert, "legacy_categories", None)
    leg_cats = (
        [c.strip() for c in leg_cats_raw.split(",") if c.strip()]
        if leg_cats_raw
        else (ev_dict.get("legacy_categories") or [])
    )
    prov_status = getattr(msg, "provenance_status", None)
    return {
        "id": alert.id,
        "risk_level": alert.risk_level,
        "score": round(alert.score, 4),
        "categories": cats,
        "legacy_categories": leg_cats,
        "category_display": ", ".join(cats) if cats else "No current illegal-trade category",
        "lifecycle_state": getattr(alert, "lifecycle_state", "active") or "active",
        "resolved_at": alert.resolved_at.isoformat() if getattr(alert, "resolved_at", None) else None,
        "resolved_by": getattr(alert, "resolved_by", None),
        "resolution_reason": getattr(alert, "resolution_reason", None),
        "evidence": ev_dict,
        "classification_state": classification_state,
        "scoring_version": scoring_ver or "legacy",
        "legacy_risk_level": ev_dict.get("legacy_risk_level"),
        "is_reviewed": alert.is_reviewed,
        "reviewed_by": alert.reviewed_by,
        "disposition": getattr(alert, "disposition", None),
        "disposition_notes": getattr(alert, "disposition_notes", None),
        "disposition_by": getattr(alert, "disposition_by", None),
        "disposition_at": alert.disposition_at.isoformat() if getattr(alert, "disposition_at", None) else None,
        "created_at": alert.created_at.isoformat(),
        "observation_count": observation_count,
        "similar_channels_count": similar_channels_count,
        "shared_identifier_channels": shared_identifier_channels or [],
        "message": {
            "id": msg.id,
            "telegram_msg_id": msg.telegram_msg_id,
            "source": getattr(msg, "source", None),
            "forwarded_from": getattr(msg, "forwarded_from", None),
            "text": msg.text if include_raw_content else None,
            "ocr_text": getattr(msg, "ocr_text", None) if include_raw_content else None,
            "raw_content_redacted": not include_raw_content,
            "evidence_hash": getattr(msg, "evidence_hash", None),
            "original_text_hash": getattr(msg, "original_text_hash", None),
            "media_hash": getattr(msg, "media_hash", None),
            "provenance_status": prov_status,
            "provenance_note": provenance_note_for_status(prov_status),
            "created_at": msg.created_at.isoformat(),
            "channel_username": msg.channel.username if msg.channel else "unknown",
            "channel_title": msg.channel.title if msg.channel else None,
            "sender_username": msg.sender_username if include_raw_content else None,
            "has_media": msg.has_media,
            "media_path": msg.media_path if include_raw_content else None,
            "identifiers": [
                {
                    "type": i.type,
                    "value": mask_identifier(i.type, i.value) if mask_identifiers else i.value,
                    "normalised": mask_identifier(i.type, i.normalised) if mask_identifiers else i.normalised,
                    "masked": mask_identifiers,
                }
                for i in msg.identifiers
            ],
        },
    }


@router.get("/stats")
async def alert_stats(
    include_historical: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    counts = await get_alert_counts(db, include_historical=include_historical)
    high = counts.get("HIGH", 0)
    med = counts.get("MEDIUM", 0)
    out = {
        "HIGH": high,
        "MEDIUM": med,
        "total": high + med,
    }
    if include_historical:
        out["LOW"] = counts.get("LOW", 0)
        out["total"] = sum(counts.values())
    # Dashboard extras: global unreviewed count + active-alert category histogram
    unrev = (
        await db.execute(
            select(func.count(Alert.id)).where(
                Alert.lifecycle_state == "active", Alert.is_reviewed == False  # noqa: E712
            )
        )
    ).scalar_one()
    out["unreviewed"] = int(unrev)
    cat_rows = (
        await db.execute(
            select(Alert.categories, func.count(Alert.id))
            .where(
                Alert.lifecycle_state == "active",
                Alert.risk_level.in_(("HIGH", "MEDIUM")),
            )
            .group_by(Alert.categories)
            .limit(500)
        )
    ).all()
    hist: Dict[str, int] = {}
    for cats_s, n in cat_rows:
        for c in (cats_s or "").split(","):
            c = c.strip()
            if c:
                hist[c] = hist.get(c, 0) + int(n)
    out["top_categories"] = [
        {"category": k, "count": v}
        for k, v in sorted(hist.items(), key=lambda kv: -kv[1])[:8]
    ]
    return out


async def _coordination_signals(db: AsyncSession, alert) -> tuple[int, List[str]]:
    msg = alert.message
    if not msg:
        return 0, []
    sim_channels = get_minhash_index().query_similar_channels(
        getattr(msg, "minhash_sig", None), msg.channel_id
    )
    # Only actor identifiers count as a shared-identifier signal; a shared
    # link or city does not mean two channels are the same actor.
    norms = [i.normalised for i in msg.identifiers if i.type in CONTACT_TYPES]
    shared_chs: List[str] = []
    if norms:
        q = await db.execute(
            select(Channel.username)
            .join(Message, Message.channel_id == Channel.id)
            .join(Identifier, Identifier.message_id == Message.id)
            .where(Identifier.normalised.in_(norms), Channel.id != msg.channel_id)
            .distinct()
        )
        shared_chs = [r[0] for r in q.all()]
    return len(sim_channels), shared_chs


@router.get("/")
async def list_alerts(
    risk_level: Optional[str] = Query(None, description="HIGH | MEDIUM | LOW"),
    reviewed: Optional[bool] = Query(None),
    lifecycle_state: Optional[str] = Query(None, description="active | suppressed | resolved_by_reclassification | legacy"),
    include_historical: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    authorized: bool = Depends(is_caller_authorized),
    db: AsyncSession = Depends(get_db),
):
    alerts = await get_alerts_paginated(
        db,
        risk_level=risk_level,
        reviewed=reviewed,
        skip=skip,
        limit=limit,
        lifecycle_state=lifecycle_state,
        include_historical=include_historical,
    )
    out = []
    for a in alerts:
        sim_cnt, shared_chs = await _coordination_signals(db, a)
        out.append(_serialise_alert(
            a,
            mask_identifiers=not authorized,
            include_raw_content=authorized,
            similar_channels_count=sim_cnt,
            shared_identifier_channels=shared_chs,
        ))
    return out


@router.get("/{alert_id}")
async def get_alert(
    alert_id: int,
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    from app.db.models import Alert, Message

    result = await db.execute(
        select(Alert)
        .options(
            selectinload(Alert.message).selectinload(Message.channel),
            selectinload(Alert.message).selectinload(Message.identifiers),
        )
        .where(Alert.id == alert_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    obs_count = 1
    if alert.message and getattr(alert.message, "evidence_hash", None):
        em = (
            await db.execute(
                select(EvidenceMessage).where(EvidenceMessage.evidence_hash == alert.message.evidence_hash)
            )
        ).scalar_one_or_none()
        if em:
            cnt = (
                await db.execute(
                    select(func.count(EvidenceObservation.id)).where(
                        EvidenceObservation.evidence_message_id == em.id
                    )
                )
            ).scalar_one()
            obs_count = max(1, cnt or 1)

    await write_audit_log(
        db,
        actor=actor,
        action="evidence_access",
        target_type="alert",
        target_id=alert.id,
        record_hash=getattr(alert.message, "evidence_hash", None),
    )
    await db.commit()
    sim_cnt, shared_chs = await _coordination_signals(db, alert)
    return _serialise_alert(
        alert,
        mask_identifiers=False,
        include_raw_content=True,
        observation_count=obs_count,
        similar_channels_count=sim_cnt,
        shared_identifier_channels=shared_chs,
    )


class ReviewPayload(BaseModel):
    reviewed_by: str = "analyst"


@router.patch("/{alert_id}/review", status_code=status.HTTP_200_OK)
async def review_alert(
    alert_id: int,
    payload: ReviewPayload,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    await mark_alert_reviewed(db, alert_id, payload.reviewed_by)
    return {"status": "reviewed", "alert_id": alert_id}
