"""
Seeds management API endpoints.

POST   /seeds/                      Create a new seed profile
GET    /seeds/                      List seed profiles with optional filters
GET    /seeds/{seed_id}             Retrieve a seed profile by ID
PATCH  /seeds/{seed_id}             Update a seed profile
DELETE /seeds/{seed_id}             Deactivate a seed profile
GET    /seeds/{seed_id}/performance Retrieve performance stats for a seed
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.retention_service import require_api_token
from app.services.seed_service import (
    create_seed,
    deactivate_seed,
    get_seed,
    get_seed_performance,
    get_seed_summary,
    list_seeds,
    sync_seed_catalogue,
    transition_seed_status,
    update_seed,
)

router = APIRouter(prefix="/seeds", tags=["seeds"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class SeedCreate(BaseModel):
    seed_text: str
    threat_category: str
    language_region: str = "en"
    intent_type: str
    priority: int = 3
    created_source: str = "manual"
    profile: str = "illegal_trade"
    seed_role: str = "indicator"
    rationale: Optional[str] = None
    approved_by: Optional[str] = None


class SeedUpdate(BaseModel):
    threat_category: Optional[str] = None
    language_region: Optional[str] = None
    intent_type: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    profile: Optional[str] = None
    seed_role: Optional[str] = None
    rationale: Optional[str] = None


class SeedStatusTransition(BaseModel):
    status: str
    actor: str
    rationale: Optional[str] = None


class SeedResponse(BaseModel):
    id: int
    seed_text: str
    seed_text_normalised: str
    threat_category: str
    language_region: str
    intent_type: str
    priority: int
    is_active: bool
    profile: str = "illegal_trade"
    seed_role: str = "indicator"
    status: str = "active"
    rationale: Optional[str] = None
    catalogue_version: Optional[str] = None
    alert_count: int = 0
    reviewed_fp_count: int = 0
    reviewed_total_count: int = 0
    created_source: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=SeedResponse, status_code=status.HTTP_201_CREATED)
async def create_seed_endpoint(
    body: SeedCreate,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
) -> SeedResponse:
    """Create a new seed profile and auto-generate its query variants."""
    try:
        seed = await create_seed(
            db,
            seed_text=body.seed_text,
            threat_category=body.threat_category,
            language_region=body.language_region,
            intent_type=body.intent_type,
            priority=body.priority,
            created_source=body.created_source,
            profile=body.profile,
            seed_role=body.seed_role,
            rationale=body.rationale,
            approved_by=body.approved_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return seed


@router.get("/summary")
async def seed_summary_endpoint(db: AsyncSession = Depends(get_db)) -> dict:
    """Return actual seed counts and category/profile/status distribution."""
    return await get_seed_summary(db)


@router.post("/sync")
async def sync_seeds_endpoint(
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run idempotent, versioned seed catalogue synchronization."""
    res = await sync_seed_catalogue(db)
    await db.commit()
    return res


@router.get("/", response_model=List[SeedResponse])
async def list_seeds_endpoint(
    is_active: Optional[bool] = Query(None),
    threat_category: Optional[str] = Query(None),
    profile: Optional[str] = Query(None),
    seed_status: Optional[str] = Query(None, alias="status"),
    seed_role: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> List[SeedResponse]:
    """Return a paginated, optionally filtered list of seed profiles."""
    seeds = await list_seeds(
        db,
        is_active=is_active,
        threat_category=threat_category,
        profile=profile,
        status=seed_status,
        seed_role=seed_role,
        skip=skip,
        limit=limit,
    )
    return list(seeds)


@router.post("/{seed_id}/status", response_model=SeedResponse)
async def transition_seed_status_endpoint(
    seed_id: int,
    body: SeedStatusTransition,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Transition seed lifecycle status (proposed -> active -> paused -> retired) with audit log."""
    try:
        seed = await transition_seed_status(
            db, seed_id, body.status, actor=body.actor, rationale=body.rationale
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if seed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seed not found")
    return seed


@router.get("/{seed_id}", response_model=SeedResponse)
async def get_seed_endpoint(
    seed_id: int,
    db: AsyncSession = Depends(get_db),
) -> SeedResponse:
    """Retrieve a single seed profile by its ID."""
    seed = await get_seed(db, seed_id)
    if seed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seed not found")
    return seed


@router.patch("/{seed_id}", response_model=SeedResponse)
async def update_seed_endpoint(
    seed_id: int,
    body: SeedUpdate,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
) -> SeedResponse:
    """Partially update a seed profile."""
    updates = body.model_dump(exclude_none=True)
    seed = await update_seed(db, seed_id, **updates)
    if seed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seed not found")
    return seed


@router.delete("/{seed_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def deactivate_seed_endpoint(
    seed_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a seed profile (soft delete)."""
    deactivated = await deactivate_seed(db, seed_id)
    if not deactivated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seed not found")


@router.get("/{seed_id}/performance")
async def get_seed_performance_endpoint(
    seed_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return execution performance statistics for a seed profile."""
    seed = await get_seed(db, seed_id)
    if seed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seed not found")
    return await get_seed_performance(db, seed_id)


@router.post("/import-defaults", status_code=status.HTTP_200_OK)
async def import_default_seeds(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Populate seed_profiles from the built-in default catalogue.
    Safe to call multiple times — already-existing seeds are skipped.
    Returns a count of newly created and skipped seeds.
    """
    from app.services.seed_defaults import DEFAULT_SEED_CATALOGUE
    created = 0
    skipped = 0
    errors = []
    for entry in DEFAULT_SEED_CATALOGUE:
        try:
            await create_seed(
                db,
                seed_text=entry["seed_text"],
                threat_category=entry["threat_category"],
                language_region=entry.get("language_region", "en"),
                intent_type=entry["intent_type"],
                priority=entry["priority"],
                created_source="default",
            )
            created += 1
        except ValueError:
            skipped += 1
        except Exception as exc:
            errors.append(str(exc))
    return {
        "created": created,
        "skipped": skipped,
        "total_in_catalogue": len(DEFAULT_SEED_CATALOGUE),
        "errors": errors[:5],
    }
