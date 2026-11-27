"""
Analyst review API — structured labelling of alerts, messages, and evidence records,
review queues (unreviewed alerts + stratified non-flagged sample), offline export,
and accuracy metrics.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.retention_service import require_api_token
from app.services.review_service import (
    VALID_CATEGORIES,
    VALID_INTENTS,
    VALID_LABELS,
    VALID_TARGET_TYPES,
    compute_false_positives_by_category_and_seed,
    compute_review_metrics,
    export_reviewed_records_offline,
    get_review_for_target,
    list_review_history,
    list_reviewed_alerts,
    list_unreviewed_alerts,
    sample_non_flagged_records,
    upsert_analyst_review,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])


# ── Request / response models ─────────────────────────────────────────────────

class AlertReviewRequest(BaseModel):
    label: str
    reviewed_by: str
    category: Optional[str] = None
    intent: Optional[str] = None
    note: Optional[str] = None
    sampling_stratum: Optional[str] = None


class TargetReviewRequest(AlertReviewRequest):
    target_type: str
    target_id: int


class ReviewOut(BaseModel):
    id: int
    target_type: str
    target_id: int
    label: str
    category: Optional[str]
    intent: Optional[str]
    reviewed_by: str
    reviewed_at: str
    note: Optional[str]
    sampling_stratum: Optional[str] = None
    classifier_score: Optional[float]
    classifier_risk_level: Optional[str]


def _serialise_review(r) -> dict:
    return {
        "id": r.id,
        "target_type": r.target_type,
        "target_id": r.target_id,
        "label": r.label,
        "category": r.category,
        "intent": r.intent,
        "reviewed_by": r.reviewed_by,
        "reviewed_at": r.reviewed_at.isoformat(),
        "note": r.note,
        "sampling_stratum": getattr(r, "sampling_stratum", None),
        "classifier_score": r.classifier_score,
        "classifier_risk_level": r.classifier_risk_level,
    }


def _serialise_alert_summary(a) -> dict:
    """Return only non-sensitive metadata for unreviewed alert listing."""
    return {
        "id": a.id,
        "risk_level": a.risk_level,
        "score": round(a.score, 4),
        "categories": a.categories.split(",") if a.categories else [],
        "created_at": a.created_at.isoformat(),
        "is_reviewed": a.is_reviewed,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/record", status_code=status.HTTP_200_OK, response_model=ReviewOut)
async def label_record(
    body: TargetReviewRequest,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Label any collected/imported record ('message', 'alert', or 'evidence_message')."""
    try:
        review = await upsert_analyst_review(
            db,
            target_type=body.target_type,
            target_id=body.target_id,
            label=body.label,
            reviewed_by=body.reviewed_by,
            category=body.category,
            intent=body.intent,
            note=body.note,
            sampling_stratum=body.sampling_stratum,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _serialise_review(review)


@router.get("/history/{target_type}/{target_id}")
async def get_target_review_history(
    target_type: str,
    target_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Return full append-only label history for a target record."""
    if target_type not in VALID_TARGET_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid target_type: {target_type}")
    history = await list_review_history(db, target_type, target_id)
    return {
        "target_type": target_type,
        "target_id": target_id,
        "count": len(history),
        "history": [_serialise_review(h) for h in history],
    }


@router.get("/sample/non-flagged")
async def get_non_flagged_stratified_sample(
    limit: int = Query(50, ge=1, le=200),
    per_stratum: int = Query(5, ge=1, le=50),
    source: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return a stratified sample of unreviewed non-flagged records (metadata only)."""
    return await sample_non_flagged_records(
        db, limit=limit, per_stratum=per_stratum, source=source
    )


@router.post("/export")
async def export_reviews_offline(
    exported_by: str = Query("analyst"),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Export reviewed records locally (ID + evidence_hash + provenance only, audit-logged)."""
    result = await export_reviewed_records_offline(db, exported_by=exported_by)
    await db.commit()
    return result


@router.post("/alerts/{alert_id}", status_code=status.HTTP_200_OK, response_model=ReviewOut)
async def label_alert(
    alert_id: int,
    body: AlertReviewRequest,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Create or update an analyst review for an alert."""
    try:
        review = await upsert_analyst_review(
            db,
            target_type="alert",
            target_id=alert_id,
            label=body.label,
            reviewed_by=body.reviewed_by,
            category=body.category,
            intent=body.intent,
            note=body.note,
            sampling_stratum=body.sampling_stratum,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _serialise_review(review)


@router.get("/alerts/unreviewed")
async def get_unreviewed_alerts(
    risk_level: Optional[str] = Query(None, description="HIGH | MEDIUM"),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return unreviewed HIGH/MEDIUM alerts (metadata only)."""
    alerts = await list_unreviewed_alerts(
        db,
        risk_level=risk_level,
        min_score=min_score,
        skip=skip,
        limit=limit,
    )
    return {
        "count": len(alerts),
        "skip": skip,
        "limit": limit,
        "results": [_serialise_alert_summary(a) for a in alerts],
    }


@router.get("/alerts/reviewed")
async def get_reviewed_alerts(
    label: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    target_type: Optional[str] = Query("alert"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Return analyst reviews, optionally filtered by target_type, label, and/or category."""
    reviews = await list_reviewed_alerts(
        db,
        label=label,
        category=category,
        target_type=target_type,
        skip=skip,
        limit=limit,
    )
    return {
        "count": len(reviews),
        "results": [_serialise_review(r) for r in reviews],
    }


@router.get("/alerts/{alert_id}", response_model=ReviewOut)
async def get_alert_review(
    alert_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Get the analyst review for a specific alert (None -> 404)."""
    review = await get_review_for_target(db, "alert", alert_id)
    if review is None:
        raise HTTPException(status_code=404, detail="No review found for this alert.")
    return _serialise_review(review)


@router.get("/metrics")
async def review_metrics(
    min_reviewed: Optional[int] = Query(None, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """
    Return precision/recall/F1/FPR computed from analyst-reviewed records only.
    Returns status='insufficient_reviewed_data' when below threshold.
    """
    return await compute_review_metrics(db, min_reviewed=min_reviewed)


@router.get("/false-positives")
async def review_false_positives(db: AsyncSession = Depends(get_db)):
    """Report reviewed false positives by category and by seed profile."""
    return await compute_false_positives_by_category_and_seed(db)


@router.get("/constants")
async def review_constants():
    """Return the valid enumeration values for label, category, intent, and target_type."""
    return {
        "target_types": sorted(VALID_TARGET_TYPES),
        "labels": sorted(VALID_LABELS),
        "categories": sorted(VALID_CATEGORIES),
        "intents": sorted(VALID_INTENTS),
    }
