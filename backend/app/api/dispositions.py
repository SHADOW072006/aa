"""
Dispositions API — analyst disposition management and audit trail.

POST /dispositions/alerts/{alert_id}          Set disposition on an alert
POST /dispositions/evidence/{evidence_id}     Set disposition on a piece of evidence
GET  /dispositions/history/{target_type}/{target_id}  Fetch audit trail

Requirements: 6.5, 6.6, REQ-API-6
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.retention_service import require_api_token
from app.services.feedback_service import (
    get_disposition_audit_trail,
    set_alert_disposition,
    set_evidence_disposition,
)

router = APIRouter(prefix="/dispositions", tags=["dispositions"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class DispositionRequest(BaseModel):
    disposition: str  # confirmed_threat | false_positive | needs_review | escalated
    notes: str = ""
    changed_by: str


class AlertDispositionResponse(BaseModel):
    id: int
    disposition: Optional[str]
    disposition_notes: Optional[str]
    disposition_by: Optional[str]
    disposition_at: Optional[str]

    model_config = {"from_attributes": True}


class AuditEntry(BaseModel):
    id: int
    previous_disposition: Optional[str]
    new_disposition: str
    changed_by: str
    changed_at: str  # ISO string
    notes: Optional[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/alerts/{alert_id}", status_code=status.HTTP_200_OK)
async def set_alert_disposition_endpoint(
    alert_id: int,
    body: DispositionRequest,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Apply an analyst disposition to an alert.
    Returns the updated alert object on success.
    """
    try:
        alert = await set_alert_disposition(
            db,
            alert_id=alert_id,
            disposition=body.disposition,
            notes=body.notes,
            changed_by=body.changed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert {alert_id} not found")

    return {
        "id": alert.id,
        "disposition": alert.disposition,
        "disposition_notes": alert.disposition_notes,
        "disposition_by": alert.disposition_by,
        "disposition_at": alert.disposition_at.isoformat() if alert.disposition_at else None,
    }


@router.post("/evidence/{evidence_id}", status_code=status.HTTP_200_OK)
async def set_evidence_disposition_endpoint(
    evidence_id: int,
    body: DispositionRequest,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Apply an analyst disposition to a piece of scan evidence.
    Returns the updated evidence object on success.
    """
    try:
        evidence = await set_evidence_disposition(
            db,
            evidence_id=evidence_id,
            disposition=body.disposition,
            notes=body.notes,
            changed_by=body.changed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Evidence {evidence_id} not found")

    return {
        "id": evidence.id,
        "disposition": evidence.disposition,
        "disposition_notes": evidence.disposition_notes,
        "disposition_by": evidence.disposition_by,
        "disposition_at": evidence.disposition_at.isoformat() if evidence.disposition_at else None,
    }


@router.get("/history/{target_type}/{target_id}", response_model=List[AuditEntry])
async def get_disposition_history(
    target_type: str,
    target_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve the full disposition audit trail for a given target.

    ``target_type`` should be ``"alert"`` or ``"evidence"``.
    """
    entries = await get_disposition_audit_trail(db, target_type=target_type, target_id=target_id)
    return entries
