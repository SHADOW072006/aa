"""
Feedback Service — analyst disposition recording, audit trail, seed feedback
metrics, and poll-tier management.

Requirements: 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 14.4
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import (
    get_disposition_history,
    get_score_for_result,
    record_disposition_change,
    update_evidence_disposition,
)
from app.db.models import (
    Alert,
    Channel,
    ChannelScoreComponents,
    QueryVariant,
    ScanEvidence,
)

# ---------------------------------------------------------------------------
# Valid disposition / tier constants
# ---------------------------------------------------------------------------

_VALID_DISPOSITIONS = frozenset(
    {"confirmed_threat", "false_positive", "needs_review", "escalated"}
)
_VALID_TIERS = frozenset({"HIGH", "MEDIUM", "LOW"})


# ---------------------------------------------------------------------------
# Alert disposition
# ---------------------------------------------------------------------------

async def set_alert_disposition(
    db: AsyncSession,
    alert_id: int,
    disposition: str,
    notes: str,
    changed_by: str,
) -> Optional[Alert]:
    """
    Update the disposition of an Alert and write an audit-trail record.

    Returns the updated Alert, or None if alert_id does not exist.
    Raises ValueError for an unrecognised disposition value.
    """
    if disposition not in _VALID_DISPOSITIONS:
        raise ValueError(
            f"Invalid disposition {disposition!r}. "
            f"Must be one of: {sorted(_VALID_DISPOSITIONS)}"
        )

    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        return None

    await record_disposition_change(
        db,
        target_type="alert",
        target_id=alert_id,
        previous_disposition=alert.disposition,
        new_disposition=disposition,
        changed_by=changed_by,
        notes=notes,
    )

    alert.disposition = disposition
    alert.disposition_notes = notes
    alert.disposition_by = changed_by
    alert.disposition_at = datetime.utcnow()

    await db.commit()
    await db.refresh(alert)
    return alert


# ---------------------------------------------------------------------------
# Evidence disposition
# ---------------------------------------------------------------------------

async def set_evidence_disposition(
    db: AsyncSession,
    evidence_id: int,
    disposition: str,
    notes: str,
    changed_by: str,
) -> Optional[ScanEvidence]:
    """
    Update the disposition of a ScanEvidence row and write an audit-trail record.

    When disposition is "confirmed_threat", increments analyst_confirmation_signal
    on the linked ChannelScoreComponents by 0.1 (capped at 1.0).

    Returns the updated ScanEvidence, or None if evidence_id does not exist.
    Raises ValueError for an unrecognised disposition value.
    """
    if disposition not in _VALID_DISPOSITIONS:
        raise ValueError(
            f"Invalid disposition {disposition!r}. "
            f"Must be one of: {sorted(_VALID_DISPOSITIONS)}"
        )

    # Load evidence to get the previous disposition before updating.
    result = await db.execute(
        select(ScanEvidence).where(ScanEvidence.id == evidence_id)
    )
    evidence = result.scalar_one_or_none()
    if evidence is None:
        return None

    await record_disposition_change(
        db,
        target_type="evidence",
        target_id=evidence_id,
        previous_disposition=evidence.disposition,
        new_disposition=disposition,
        changed_by=changed_by,
        notes=notes,
    )

    evidence = await update_evidence_disposition(
        db, evidence_id, disposition, notes, changed_by
    )

    # Analyst confirmation signal boost for confirmed threats.
    if disposition == "confirmed_threat" and evidence is not None:
        channel_scan_result_id = evidence.channel_scan_result_id
        if channel_scan_result_id is not None:
            score_components = await get_score_for_result(db, channel_scan_result_id)
            if score_components is not None:
                score_components.analyst_confirmation_signal = min(
                    1.0,
                    score_components.analyst_confirmation_signal + 0.1,
                )
                await db.flush()

    await db.commit()
    if evidence is not None:
        await db.refresh(evidence)
    return evidence


# ---------------------------------------------------------------------------
# Disposition audit trail
# ---------------------------------------------------------------------------

async def get_disposition_audit_trail(
    db: AsyncSession,
    target_type: str,
    target_id: int,
) -> list[dict]:
    """
    Return the full disposition history for a target object as a list of dicts.
    """
    history = await get_disposition_history(db, target_type, target_id)
    return [
        {
            "id": dh.id,
            "previous_disposition": dh.previous_disposition,
            "new_disposition": dh.new_disposition,
            "changed_by": dh.changed_by,
            "changed_at": dh.changed_at.isoformat(),
            "notes": dh.notes,
        }
        for dh in history
    ]


# ---------------------------------------------------------------------------
# Seed feedback metrics
# ---------------------------------------------------------------------------

async def compute_seed_feedback_metrics(
    db: AsyncSession,
    seed_profile_id: int,
) -> dict:
    """
    Aggregate analyst-feedback performance metrics for a seed profile.

    Returns a dict with keys:
        seed_profile_id, total_evidence, confirmed_threats,
        false_positives, precision
    """
    # Collect all QueryVariant ids for this seed.
    variant_result = await db.execute(
        select(QueryVariant.id).where(
            QueryVariant.seed_profile_id == seed_profile_id
        )
    )
    variant_ids = [row[0] for row in variant_result.all()]

    if not variant_ids:
        return {
            "seed_profile_id": seed_profile_id,
            "total_evidence": 0,
            "confirmed_threats": 0,
            "false_positives": 0,
            "precision": None,
        }

    # Total evidence rows linked to any of those variants.
    total_result = await db.execute(
        select(func.count(ScanEvidence.id)).where(
            ScanEvidence.query_variant_id.in_(variant_ids)
        )
    )
    total_evidence: int = total_result.scalar_one() or 0

    # Confirmed threats.
    confirmed_result = await db.execute(
        select(func.count(ScanEvidence.id)).where(
            ScanEvidence.query_variant_id.in_(variant_ids),
            ScanEvidence.disposition == "confirmed_threat",
        )
    )
    confirmed: int = confirmed_result.scalar_one() or 0

    # False positives.
    fp_result = await db.execute(
        select(func.count(ScanEvidence.id)).where(
            ScanEvidence.query_variant_id.in_(variant_ids),
            ScanEvidence.disposition == "false_positive",
        )
    )
    false_positives: int = fp_result.scalar_one() or 0

    denominator = confirmed + false_positives
    precision: Optional[float] = (confirmed / denominator) if denominator > 0 else None

    return {
        "seed_profile_id": seed_profile_id,
        "total_evidence": total_evidence,
        "confirmed_threats": confirmed,
        "false_positives": false_positives,
        "precision": precision,
    }


# ---------------------------------------------------------------------------
# Poll-tier management
# ---------------------------------------------------------------------------

async def update_poll_tier(
    db: AsyncSession,
    channel_id: int,
    new_tier: str,
) -> Optional[Channel]:
    """
    Update poll_tier on a Channel.

    Returns the updated Channel, or None if channel_id does not exist.
    Raises ValueError for an unrecognised tier value.
    """
    if new_tier not in _VALID_TIERS:
        raise ValueError(
            f"Invalid poll tier {new_tier!r}. Must be one of: {sorted(_VALID_TIERS)}"
        )

    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if channel is None:
        return None

    channel.poll_tier = new_tier
    await db.commit()
    await db.refresh(channel)
    return channel
