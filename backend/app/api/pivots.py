"""
Pivot candidate review endpoints.

GET  /pivots/                        List pending pivot candidates
POST /pivots/{pivot_id}/approve      Approve a pivot candidate
POST /pivots/{pivot_id}/reject       Reject a pivot candidate

Requirements: 4.5, 4.6, REQ-API-4
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.pivot_service import approve_pivot, list_pending_pivots, reject_pivot
from app.services.retention_service import require_api_token

router = APIRouter(prefix="/pivots", tags=["pivots"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PivotResponse(BaseModel):
    id: int
    source_channel_username: str
    candidate_type: str
    candidate_value: str
    status: str
    created_at: datetime
    evaluated_at: datetime | None
    evaluated_by: str | None
    notes: str | None

    class Config:
        from_attributes = True


class PivotAction(BaseModel):
    evaluated_by: str
    notes: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=List[PivotResponse])
async def get_pending_pivots(
    skip: int = 0,
    limit: int = 100,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """List all pending pivot candidates."""
    return await list_pending_pivots(db, skip=skip, limit=limit)


@router.post("/{pivot_id}/approve", response_model=PivotResponse)
async def approve_pivot_candidate(
    pivot_id: int,
    body: PivotAction,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pivot candidate by ID."""
    result = await approve_pivot(db, pivot_id, body.evaluated_by, body.notes)
    if result is None:
        raise HTTPException(status_code=404, detail="Pivot candidate not found")
    return result


@router.post("/{pivot_id}/reject", response_model=PivotResponse)
async def reject_pivot_candidate(
    pivot_id: int,
    body: PivotAction,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Reject a pivot candidate by ID."""
    result = await reject_pivot(db, pivot_id, body.evaluated_by, body.notes)
    if result is None:
        raise HTTPException(status_code=404, detail="Pivot candidate not found")
    return result
