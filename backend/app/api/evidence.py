"""
Evidence API endpoints.

GET /evidence/            List evidence records filtered by scan_job_id or channel_username
GET /evidence/{id}        Fetch a single evidence record by primary key

Requirements: 3.5, 3.6, REQ-API-3
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import get_evidence_for_channel, get_evidence_for_scan
from app.db.database import get_db
from app.db.models import ScanEvidence
from app.services.retention_service import require_api_token

router = APIRouter(prefix="/evidence", tags=["evidence"])


class EvidenceResponse(BaseModel):
    id: int
    scan_job_id: int
    channel_username: str
    telegram_message_id: int
    message_timestamp: Optional[datetime]
    raw_text: Optional[str]
    normalised_text: Optional[str]
    classifier_score: float
    risk_level: str
    severity_tier: str
    categories: Optional[str]
    matched_terms: Optional[str]
    seed_term: Optional[str]
    disposition: Optional[str]
    disposition_notes: Optional[str]
    disposition_by: Optional[str]
    disposition_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.get("/", response_model=List[EvidenceResponse])
async def list_evidence(
    scan_job_id: Optional[int] = Query(None),
    channel_username: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Return evidence records.  Exactly one of *scan_job_id* or *channel_username*
    must be supplied; both omitted returns HTTP 400.
    """
    if scan_job_id is not None:
        return await get_evidence_for_scan(db, scan_job_id, skip, limit)
    elif channel_username is not None:
        return await get_evidence_for_channel(db, channel_username, skip, limit)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide scan_job_id or channel_username",
        )


@router.get("/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(
    evidence_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single evidence record by its primary key."""
    evidence = await db.get(ScanEvidence, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return evidence
