"""
Evidence V2 API — canonical message records and classification observations.

GET  /evidence/v2/messages/                       List with filters
GET  /evidence/v2/messages/{id}                   Single canonical message
GET  /evidence/v2/messages/{id}/observations      All classification events
POST /evidence/v2/messages/{id}/disposition        Set analyst disposition

Requirements: Req 11
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import (
    get_evidence_message,
    get_observations_for_message,
    list_evidence_messages,
    set_evidence_message_disposition,
)
from app.db.database import get_db
from app.services.evidence_hashing import provenance_note_for_status
from app.services.retention_service import require_api_token

router = APIRouter(prefix="/evidence/v2", tags=["evidence-v2"])


# ── Pydantic response schemas ─────────────────────────────────────────────────

class EvidenceMessageOut(BaseModel):
    id: int
    channel_username: str
    telegram_message_id: int
    message_timestamp: Optional[datetime] = None
    raw_text: Optional[str] = None
    ocr_text: Optional[str] = None
    normalised_text: Optional[str] = None
    ocr_outcome: Optional[str] = None
    ocr_skip_reason: Optional[str] = None
    media_path: Optional[str] = None
    evidence_hash: Optional[str] = None
    original_text_hash: Optional[str] = None
    media_hash: Optional[str] = None
    provenance_status: Optional[str] = None
    provenance_note: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime
    disposition: Optional[str] = None
    disposition_notes: Optional[str] = None
    disposition_by: Optional[str] = None
    disposition_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EvidenceObservationOut(BaseModel):
    id: int
    evidence_message_id: int
    scan_job_id: Optional[int] = None
    channel_scan_result_id: Optional[int] = None
    seed_profile_id: Optional[int] = None
    query_variant_id: Optional[int] = None
    source_type: str
    classifier_version: str
    score: float
    risk_level: str
    severity_tier: str
    categories: Optional[str] = None
    matched_terms: Optional[str] = None
    classified_at: datetime

    model_config = {"from_attributes": True}


class EvidenceMessageDetail(EvidenceMessageOut):
    latest_observation: Optional[EvidenceObservationOut] = None


class DispositionRequest(BaseModel):
    disposition: str
    notes: Optional[str] = None
    changed_by: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/messages/", response_model=List[EvidenceMessageOut])
async def list_messages(
    channel_username: Optional[str] = Query(None),
    disposition: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """List canonical evidence messages with optional filters."""
    messages = await list_evidence_messages(
        db,
        channel_username=channel_username,
        disposition=disposition,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=limit,
    )
    out = []
    for ev in messages:
        item = EvidenceMessageOut.model_validate(ev)
        item.provenance_note = provenance_note_for_status(getattr(ev, "provenance_status", None))
        out.append(item)
    return out


@router.get("/messages/{evidence_id}", response_model=EvidenceMessageDetail)
async def get_message(
    evidence_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Get a single canonical evidence message with its latest observation."""
    ev = await get_evidence_message(db, evidence_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Evidence message not found")
    observations = await get_observations_for_message(db, evidence_id)
    latest = observations[0] if observations else None
    result = EvidenceMessageDetail.model_validate(ev)
    result.provenance_note = provenance_note_for_status(getattr(ev, "provenance_status", None))
    result.latest_observation = EvidenceObservationOut.model_validate(latest) if latest else None
    return result


@router.get("/messages/{evidence_id}/observations", response_model=List[EvidenceObservationOut])
async def get_observations(
    evidence_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """List all classification observations for a canonical evidence message, newest first."""
    ev = await get_evidence_message(db, evidence_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Evidence message not found")
    observations = await get_observations_for_message(db, evidence_id)
    return observations


@router.post("/messages/{evidence_id}/disposition")
async def set_disposition(
    evidence_id: int,
    body: DispositionRequest,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Set analyst disposition on a canonical evidence message."""
    try:
        ev = await set_evidence_message_disposition(
            db,
            evidence_message_id=evidence_id,
            disposition=body.disposition,
            notes=body.notes,
            changed_by=body.changed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if ev is None:
        raise HTTPException(status_code=404, detail="Evidence message not found")
    return {
        "id": ev.id,
        "disposition": ev.disposition,
        "disposition_notes": ev.disposition_notes,
        "disposition_by": ev.disposition_by,
        "disposition_at": ev.disposition_at.isoformat() if ev.disposition_at else None,
    }
