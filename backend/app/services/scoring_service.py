"""
Composite channel scoring service.
Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.crud import upsert_channel_score
from app.db.models import ChannelScanResult, ChannelScoreComponents


def compute_composite_score(
    evidence_list: list[dict],
    valid_pivot_count: int = 0,
    analyst_signal: float = 0.0,
) -> dict:
    """
    Compute a composite threat score from a list of evidence dicts.

    Each dict may contain:
        classifier_score    float
        risk_level          str
        severity_tier       str
        message_timestamp   datetime | None

    Returns a dict with all component scores and the final composite_score.
    """
    total = len(evidence_list)

    # 1. max_message_score
    if total == 0:
        max_message_score = 0.0
    else:
        max_message_score = min(
            max(e.get("classifier_score", 0.0) for e in evidence_list),
            1.0,
        )

    # 2. high_confidence_message_count / normalised
    high_msg_raw = sum(
        1 for e in evidence_list if e.get("classifier_score", 0.0) >= 0.7
    )
    cap_high = settings.COMPOSITE_HIGH_MSG_CAP
    high_msg_norm = min(high_msg_raw, cap_high) / cap_high if cap_high > 0 else 0.0

    # 3. distinct_incident_count / normalised
    incident_tiers = {
        e.get("severity_tier")
        for e in evidence_list
        if e.get("severity_tier") in ("P1", "P2")
    }
    incident_raw = len(incident_tiers)
    cap_incident = settings.COMPOSITE_INCIDENT_CAP
    incident_norm = (
        min(incident_raw, cap_incident) / cap_incident if cap_incident > 0 else 0.0
    )

    # 4. recency_weight
    now = datetime.now(tz=timezone.utc)
    most_recent: Optional[datetime] = None
    for e in evidence_list:
        ts = e.get("message_timestamp")
        if ts is None:
            continue
        # Ensure tz-aware for comparison
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if most_recent is None or ts > most_recent:
                most_recent = ts

    if most_recent is None:
        recency_weight = 0.2
    else:
        delta_seconds = (now - most_recent).total_seconds()
        if delta_seconds <= 86_400:          # 24 h
            recency_weight = 1.0
        elif delta_seconds <= 7 * 86_400:    # 7 days
            recency_weight = 0.7
        elif delta_seconds <= 30 * 86_400:   # 30 days
            recency_weight = 0.4
        else:
            recency_weight = 0.2

    # 5. identifier_density
    if total == 0:
        identifier_density = 0.0
    else:
        dense_count = sum(
            1
            for e in evidence_list
            if e.get("risk_level") in ("critical", "high")
            and e.get("classifier_score", 0.0) >= 0.8
        )
        identifier_density = dense_count / total

    # 6. valid_pivot_norm
    cap_pivot = settings.COMPOSITE_PIVOT_CAP
    valid_pivot_norm = (
        min(valid_pivot_count, cap_pivot) / cap_pivot if cap_pivot > 0 else 0.0
    )

    # 7. composite_score (weighted sum, clamped to [0, 1])
    composite_score = (
        0.30 * max_message_score
        + 0.20 * high_msg_norm
        + 0.15 * incident_norm
        + 0.15 * recency_weight
        + 0.10 * identifier_density
        + 0.05 * valid_pivot_norm
        + 0.05 * min(analyst_signal, 1.0)
    )
    composite_score = max(0.0, min(1.0, composite_score))

    return {
        "composite_score": composite_score,
        "max_message_score": max_message_score,
        "high_confidence_message_count": high_msg_raw,
        "distinct_incident_count": incident_raw,
        "recency_weight": recency_weight,
        "identifier_density": identifier_density,
        "valid_pivot_count": valid_pivot_count,
        "analyst_confirmation_signal": min(analyst_signal, 1.0),
    }


async def save_channel_score(
    db: AsyncSession,
    channel_scan_result_id: int,
    score_dict: dict,
) -> ChannelScoreComponents:
    """
    Persist a score_dict (from compute_composite_score) for the given
    ChannelScanResult row.

    * Upserts a ChannelScoreComponents record.
    * Updates composite_score on the parent ChannelScanResult row.
    * Returns the ChannelScoreComponents ORM object.
    """
    score_obj = await upsert_channel_score(
        db,
        channel_scan_result_id=channel_scan_result_id,
        **score_dict,
    )

    await db.execute(
        update(ChannelScanResult)
        .where(ChannelScanResult.id == channel_scan_result_id)
        .values(composite_score=score_dict["composite_score"])
    )

    return score_obj
